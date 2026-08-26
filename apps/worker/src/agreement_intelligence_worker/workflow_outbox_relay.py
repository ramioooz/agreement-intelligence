"""Lease and relay committed review-workflow outbox events to SQS."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError

logger = logging.getLogger("agreement_intelligence.worker")


class WorkflowEventPublisher(Protocol):
    def publish(self, event: dict[str, object]) -> None: ...


class SQSWorkflowEventPublisher:
    def __init__(self, *, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def publish(self, event: dict[str, object]) -> None:
        request: dict[str, object] = {
            "QueueUrl": self._queue_url,
            "MessageBody": json.dumps(
                {
                    "kind": "review-workflow",
                    "event_id": str(event["id"]),
                    "organization_id": str(event["organization_id"]),
                    "workspace_id": str(event["workspace_id"]),
                },
                sort_keys=True,
            ),
        }
        if self._queue_url.rsplit("/", 1)[-1].endswith(".fifo"):
            request["MessageGroupId"] = str(event["workflow_id"])
            request["MessageDeduplicationId"] = str(event["idempotency_key"])
        self._client.send_message(**request)


class WorkflowOutboxRelay:
    def __init__(
        self,
        engine: Engine,
        publisher: WorkflowEventPublisher,
        *,
        owner: str | None = None,
        lease_seconds: int = 30,
    ) -> None:
        self._engine = engine
        self._publisher = publisher
        self._owner = owner or f"workflow-relay-{uuid4()}"
        self._lease_seconds = lease_seconds

    def relay_once(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        lease_expires = current + timedelta(seconds=self._lease_seconds)
        lock = " FOR UPDATE SKIP LOCKED" if self._engine.dialect.name == "postgresql" else ""
        with self._engine.begin() as connection:
            organizations: list[object | None] = [None]
            if self._engine.dialect.name == "postgresql":
                organizations = list(
                    connection.execute(text("SELECT id FROM organizations ORDER BY id")).scalars()
                )
            event = None
            for organization_id in organizations:
                organization_filter = ""
                parameters: dict[str, object] = {"now": current}
                if organization_id is not None:
                    connection.execute(
                        text("SELECT set_config('app.organization_id', :id, true)"),
                        {"id": str(organization_id)},
                    )
                    organization_filter = " AND organization_id = :organization_id"
                    parameters["organization_id"] = organization_id
                event = (
                    connection.execute(
                        text(
                            """
                    SELECT id, workflow_id, organization_id, workspace_id,
                           idempotency_key, attempt_count
                    FROM review_workflow_outbox
                    WHERE delivered_at IS NULL
                      AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                      AND (lease_expires_at IS NULL OR lease_expires_at <= :now)
                    """
                            + organization_filter
                            + """
                    ORDER BY created_at, id
                    LIMIT 1
                    """
                            + lock
                        ),
                        parameters,
                    )
                    .mappings()
                    .one_or_none()
                )
                if event is not None:
                    break
            if event is None:
                return False
            connection.execute(
                text(
                    """
                    UPDATE review_workflow_outbox
                    SET lease_owner = :owner, lease_expires_at = :lease_expires
                    WHERE id = :id
                    """
                ),
                {"owner": self._owner, "lease_expires": lease_expires, "id": event["id"]},
            )
            claimed = dict(event)
        try:
            self._publisher.publish(claimed)
        except Exception as error:
            attempt = int(claimed["attempt_count"]) + 1
            retry_at = current + timedelta(seconds=min(300, 2 ** min(attempt, 8)))
            with self._engine.begin() as connection:
                self._scope(connection, claimed["organization_id"])
                connection.execute(
                    text(
                        """
                        UPDATE review_workflow_outbox
                        SET attempt_count = :attempt, next_attempt_at = :retry_at,
                            last_error = :last_error, lease_owner = NULL, lease_expires_at = NULL
                        WHERE id = :id AND lease_owner = :owner AND delivered_at IS NULL
                        """
                    ),
                    {
                        "attempt": attempt,
                        "retry_at": retry_at,
                        "last_error": str(error)[:512],
                        "id": claimed["id"],
                        "owner": self._owner,
                    },
                )
            logger.warning(
                "review workflow outbox publish failed",
                extra={"workflow_event_id": str(claimed["id"]), "attempt_count": attempt},
            )
            return False
        with self._engine.begin() as connection:
            self._scope(connection, claimed["organization_id"])
            connection.execute(
                text(
                    """
                    UPDATE review_workflow_outbox
                    SET delivered_at = :now, lease_owner = NULL, lease_expires_at = NULL,
                        last_error = NULL
                    WHERE id = :id AND lease_owner = :owner AND delivered_at IS NULL
                    """
                ),
                {"now": current, "id": claimed["id"], "owner": self._owner},
            )
        return True

    def _scope(self, connection: Any, organization_id: object) -> None:
        if self._engine.dialect.name == "postgresql":
            connection.execute(
                text("SELECT set_config('app.organization_id', :id, true)"),
                {"id": str(organization_id)},
            )


async def run_workflow_outbox_relay(
    stop_event: asyncio.Event,
    relay: WorkflowOutboxRelay,
    *,
    idle_seconds: float = 1.0,
    database_backoff_base_seconds: float = 1.0,
    database_backoff_max_seconds: float = 30.0,
) -> None:
    database_failures = 0
    while not stop_event.is_set():
        try:
            delivered = relay.relay_once()
        except OperationalError as error:
            database_failures += 1
            logger.warning(
                "review workflow outbox database operation failed",
                extra={"attempt_count": database_failures, "error_type": type(error).__name__},
            )
            delay = min(
                database_backoff_max_seconds,
                database_backoff_base_seconds * (2 ** min(database_failures - 1, 8)),
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            continue
        except DBAPIError as error:
            if not error.connection_invalidated:
                raise
            database_failures += 1
            delay = min(
                database_backoff_max_seconds,
                database_backoff_base_seconds * (2 ** min(database_failures - 1, 8)),
            )
            logger.warning(
                "review workflow outbox database connection invalidated",
                extra={"attempt_count": database_failures},
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            continue
        database_failures = 0
        if delivered:
            continue
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=idle_seconds)
