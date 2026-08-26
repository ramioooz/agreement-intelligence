import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    and_,
    insert,
    or_,
    select,
    text,
    update,
)

deletion_metadata = MetaData()
deletion_requests = Table(
    "agreement_deletion_requests",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("actor_id", Uuid(as_uuid=True), nullable=False),
    Column("title", String(500), nullable=False),
    Column("agreement_type", String(100), nullable=False),
    Column("file_checksums", JSON, nullable=False),
    Column("state", String(32), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("retry_cycle", Integer, nullable=False),
    Column("claim_token", Uuid(as_uuid=True), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("failure_category", String(64), nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("processing_started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("failed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
deletion_objects = Table(
    "agreement_deletion_objects",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("deletion_id", Uuid(as_uuid=True), nullable=False),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("category", String(32), nullable=False),
    Column("object_key", String(1024), nullable=False),
    Column("state", String(32), nullable=False),
    Column("last_error", String(500), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
deletion_outbox = Table(
    "agreement_deletion_outbox",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("deletion_id", Uuid(as_uuid=True), nullable=False),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("lease_token", Uuid(as_uuid=True), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("last_error", String(500), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
deletion_audit_events = Table(
    "agreement_deletion_audit_events",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("title", String(500), nullable=False),
    Column("agreement_type", String(100), nullable=False),
    Column("file_checksums", JSON, nullable=False),
    Column("actor_id", Uuid(as_uuid=True), nullable=False),
    Column("deletion_id", Uuid(as_uuid=True), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("retry_cycle", Integer, nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
document_object_registry = Table(
    "document_object_registry",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("object_key", String(1024), nullable=False),
    Column("checksum", String(255), nullable=True),
    Column("content_type", String(100), nullable=True),
    Column("byte_size", Integer, nullable=True),
    Column("state", String(32), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
processing_artifact_intents = Table(
    "processing_artifact_intents",
    deletion_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("job_id", Uuid(as_uuid=True), nullable=False),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("profile", String(100), nullable=False),
    Column("category", String(32), nullable=False),
    Column("artifact_key", String(1024), nullable=False),
    Column("state", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class AgreementDeletion:
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    agreement_id: UUID
    attempt_count: int
    claim_token: UUID


@dataclass(frozen=True)
class AgreementDeletionObject:
    id: UUID
    category: str
    object_key: str
    state: str


@dataclass(frozen=True)
class ClaimedDeletionOutbox:
    id: UUID
    deletion_id: UUID
    agreement_id: UUID
    organization_id: UUID
    workspace_id: UUID
    lease_token: UUID
    attempt_count: int = 1


class AgreementDeletionRepository(Protocol):
    def claim(
        self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID
    ) -> AgreementDeletion | None: ...
    def pending_objects(self, deletion: AgreementDeletion) -> list[AgreementDeletionObject]: ...
    def delete_source_if_unreferenced(
        self,
        deletion: AgreementDeletion,
        item: AgreementDeletionObject,
        delete_object: Callable[[str], None],
    ) -> None: ...
    def mark_deleted(self, deletion: AgreementDeletion, item: AgreementDeletionObject) -> None: ...
    def complete_and_purge(self, deletion: AgreementDeletion) -> None: ...
    def retry_database_cleanup(
        self, deletion: AgreementDeletion, *, message: str, next_retry_at: datetime
    ) -> None: ...
    def fail_database_cleanup(self, deletion: AgreementDeletion, *, message: str) -> None: ...
    def retry(
        self, deletion: AgreementDeletion, *, object_id: UUID, message: str, next_retry_at: datetime
    ) -> None: ...
    def fail(self, deletion: AgreementDeletion, *, object_id: UUID, message: str) -> None: ...


class AgreementDeletionOutboxRepository(Protocol):
    def organization_ids(self) -> list[UUID]: ...
    def recover_stale_deletions(self, organization_id: UUID) -> int: ...
    def claim_due_outbox(self, organization_id: UUID) -> ClaimedDeletionOutbox | None: ...
    def mark_outbox_delivered(self, message: ClaimedDeletionOutbox) -> None: ...
    def release_outbox(
        self, message: ClaimedDeletionOutbox, *, next_attempt_at: datetime
    ) -> None: ...


class ObjectStorage(Protocol):
    def delete(self, key: str) -> None: ...


class AgreementDeletionQueue(Protocol):
    def enqueue_deletion(
        self,
        deletion_id: UUID,
        *,
        agreement_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        delay_seconds: int,
    ) -> None: ...


@dataclass(frozen=True)
class DeletionRetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: int = 2
    max_delay_seconds: int = 300

    def may_retry(self, attempt_count: int) -> bool:
        return attempt_count < self.max_attempts

    def delay_seconds(self, attempt_count: int) -> int:
        return int(
            min(self.base_delay_seconds * (2 ** max(attempt_count - 1, 0)), self.max_delay_seconds)
        )


class ObjectCleanupError(RuntimeError):
    pass


class AgreementDeletionProcessor:
    def __init__(
        self,
        repository: AgreementDeletionRepository,
        storage: ObjectStorage,
        *,
        retry_policy: DeletionRetryPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._retry_policy = retry_policy or DeletionRetryPolicy()

    def handle(self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID) -> None:
        deletion = self._repository.claim(
            deletion_id, organization_id=organization_id, workspace_id=workspace_id
        )
        if deletion is None:
            return
        for item in self._repository.pending_objects(deletion):
            try:
                _validate_owned_key(deletion, item)
                if item.category == "source":
                    self._repository.delete_source_if_unreferenced(
                        deletion, item, self._delete_object
                    )
                else:
                    self._delete_object(item.object_key)
                    self._repository.mark_deleted(deletion, item)
            except ObjectCleanupError:
                message = "Agreement object cleanup failed"
                if not self._retry_policy.may_retry(deletion.attempt_count):
                    self._repository.fail(deletion, object_id=item.id, message=message)
                    return
                delay_seconds = self._retry_policy.delay_seconds(deletion.attempt_count)
                self._repository.retry(
                    deletion,
                    object_id=item.id,
                    message=message,
                    next_retry_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
                )
                return
        # A persisted retry can be acknowledged; total outages propagate and leave delivery open.
        try:
            self._repository.complete_and_purge(deletion)
        except Exception:
            message = "Agreement database cleanup failed"
            if not self._retry_policy.may_retry(deletion.attempt_count):
                self._repository.fail_database_cleanup(deletion, message=message)
                return
            self._repository.retry_database_cleanup(
                deletion,
                message=message,
                next_retry_at=datetime.now(UTC)
                + timedelta(seconds=self._retry_policy.delay_seconds(deletion.attempt_count)),
            )

    def _delete_object(self, key: str) -> None:
        try:
            self._storage.delete(key)
        except Exception as error:
            raise ObjectCleanupError("object storage deletion failed") from error


class AgreementDeletionOutboxSweeper:
    def __init__(
        self,
        repository: AgreementDeletionOutboxRepository,
        queue: AgreementDeletionQueue,
        *,
        retry_policy: DeletionRetryPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._retry_policy = retry_policy or DeletionRetryPolicy()

    def sweep_once(self) -> int:
        delivered = 0
        for organization_id in self._repository.organization_ids():
            self._repository.recover_stale_deletions(organization_id)
            while (message := self._repository.claim_due_outbox(organization_id)) is not None:
                try:
                    self._queue.enqueue_deletion(
                        message.deletion_id,
                        agreement_id=message.agreement_id,
                        organization_id=message.organization_id,
                        workspace_id=message.workspace_id,
                        delay_seconds=0,
                    )
                except Exception:
                    self._repository.release_outbox(
                        message,
                        next_attempt_at=datetime.now(UTC)
                        + timedelta(
                            seconds=self._retry_policy.delay_seconds(message.attempt_count)
                        ),
                    )
                    break
                self._repository.mark_outbox_delivered(message)
                delivered += 1
        return delivered


async def run_deletion_outbox_loop(
    stop_event: asyncio.Event,
    sweeper: AgreementDeletionOutboxSweeper,
    *,
    poll_interval_seconds: float = 1.0,
) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(sweeper.sweep_once)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            continue


class SQLAlchemyAgreementDeletionRepository:
    def __init__(self, engine: Engine, *, lease_seconds: int = 120) -> None:
        self._engine = engine
        self._lease_seconds = lease_seconds

    def claim(
        self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID
    ) -> AgreementDeletion | None:
        now = datetime.now(UTC)
        claim_token = uuid4()
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id)
            record = (
                connection.execute(
                    select(deletion_requests)
                    .where(
                        deletion_requests.c.id == deletion_id,
                        deletion_requests.c.organization_id == organization_id,
                        deletion_requests.c.workspace_id == workspace_id,
                        deletion_requests.c.next_attempt_at <= now,
                    )
                    .where(
                        or_(
                            deletion_requests.c.state.in_(("accepted", "retrying")),
                            and_(
                                deletion_requests.c.state == "processing",
                                deletion_requests.c.lease_expires_at <= now,
                            ),
                        )
                    )
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if record is None:
                return None
            attempt_count = int(record["attempt_count"]) + 1
            connection.execute(
                update(deletion_requests)
                .where(deletion_requests.c.id == deletion_id)
                .values(
                    state="processing",
                    attempt_count=attempt_count,
                    claim_token=claim_token,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                    processing_started_at=record["processing_started_at"] or now,
                    failure_category=None,
                    failure_message=None,
                    updated_at=now,
                )
            )
            return AgreementDeletion(
                id=deletion_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=cast(UUID, record["agreement_id"]),
                attempt_count=attempt_count,
                claim_token=claim_token,
            )

    def pending_objects(self, deletion: AgreementDeletion) -> list[AgreementDeletionObject]:
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            if not self._claim_is_current(connection, deletion, lock=False):
                return []
            records = connection.execute(
                select(deletion_objects)
                .where(
                    deletion_objects.c.deletion_id == deletion.id,
                    deletion_objects.c.state == "pending",
                )
                .order_by(deletion_objects.c.id)
            ).mappings()
            return [
                AgreementDeletionObject(
                    id=cast(UUID, record["id"]),
                    category=str(record["category"]),
                    object_key=str(record["object_key"]),
                    state=str(record["state"]),
                )
                for record in records
            ]

    def delete_source_if_unreferenced(
        self,
        deletion: AgreementDeletion,
        item: AgreementDeletionObject,
        delete_object: Callable[[str], None],
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            self._lock_object_key(connection, item.object_key)
            if not self._claim_is_current(connection, deletion, lock=True):
                raise RuntimeError("agreement deletion lease was lost")
            current = connection.scalar(
                select(deletion_objects.c.state)
                .where(
                    deletion_objects.c.id == item.id, deletion_objects.c.deletion_id == deletion.id
                )
                .with_for_update()
            )
            if current != "pending":
                return
            shared = connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM agreement_versions AS version
                        JOIN agreements AS agreement
                          ON agreement.id = version.agreement_id
                        WHERE version.storage_key = :object_key
                          AND version.agreement_id <> :agreement_id
                          AND version.organization_id = :organization_id
                          AND version.workspace_id = :workspace_id
                          AND agreement.deletion_requested_at IS NULL
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM agreements AS agreement
                        CROSS JOIN LATERAL jsonb_array_elements(
                            COALESCE(agreement.files::jsonb, '[]'::jsonb)
                        ) AS file
                        WHERE file ->> 'storage_key' = :object_key
                          AND agreement.id <> :agreement_id
                          AND agreement.organization_id = :organization_id
                          AND agreement.workspace_id = :workspace_id
                          AND agreement.deletion_requested_at IS NULL
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM document_object_registry AS registry
                        JOIN agreement_deletion_requests AS request
                          ON request.id = :deletion_id
                        WHERE registry.organization_id = :organization_id
                          AND registry.workspace_id = :workspace_id
                          AND registry.object_key = :object_key
                          AND registry.state = 'available'
                          AND registry.updated_at > request.accepted_at
                    )
                    """
                ),
                {
                    "object_key": item.object_key,
                    "agreement_id": deletion.agreement_id,
                    "deletion_id": deletion.id,
                    "organization_id": deletion.organization_id,
                    "workspace_id": deletion.workspace_id,
                },
            )
            state = "preserved" if shared else "deleted"
            if not shared:
                delete_object(item.object_key)
                connection.execute(
                    text(
                        """
                        INSERT INTO document_object_registry (
                            id, organization_id, workspace_id, object_key,
                            state, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :workspace_id, :object_key,
                            'deleted', :now, :now
                        )
                        ON CONFLICT (organization_id, workspace_id, object_key)
                        DO UPDATE SET state = 'deleted', updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": uuid4(),
                        "organization_id": deletion.organization_id,
                        "workspace_id": deletion.workspace_id,
                        "object_key": item.object_key,
                        "now": now,
                    },
                )
            self._finish_object(connection, deletion, item.id, state=state, now=now)

    def mark_deleted(self, deletion: AgreementDeletion, item: AgreementDeletionObject) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            if not self._claim_is_current(connection, deletion, lock=True):
                raise RuntimeError("agreement deletion lease was lost")
            self._finish_object(connection, deletion, item.id, state="deleted", now=now)

    def retry(
        self, deletion: AgreementDeletion, *, object_id: UUID, message: str, next_retry_at: datetime
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            if not self._claim_is_current(connection, deletion, lock=True):
                return
            connection.execute(
                update(deletion_objects)
                .where(
                    deletion_objects.c.id == object_id,
                    deletion_objects.c.deletion_id == deletion.id,
                )
                .values(last_error=message, updated_at=now)
            )
            connection.execute(
                update(deletion_requests)
                .where(
                    deletion_requests.c.id == deletion.id,
                    deletion_requests.c.claim_token == deletion.claim_token,
                )
                .values(
                    state="retrying",
                    claim_token=None,
                    lease_expires_at=None,
                    next_attempt_at=next_retry_at,
                    failure_category="object_storage",
                    failure_message=message,
                    updated_at=now,
                )
            )
            connection.execute(
                update(deletion_outbox)
                .where(deletion_outbox.c.deletion_id == deletion.id)
                .values(
                    delivered_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=next_retry_at,
                    last_error=message,
                    updated_at=now,
                )
            )

    def fail(self, deletion: AgreementDeletion, *, object_id: UUID, message: str) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            record = self._locked_claim(connection, deletion)
            if record is None:
                return
            connection.execute(
                update(deletion_objects)
                .where(
                    deletion_objects.c.id == object_id,
                    deletion_objects.c.deletion_id == deletion.id,
                )
                .values(last_error=message, updated_at=now)
            )
            connection.execute(
                update(deletion_requests)
                .where(
                    deletion_requests.c.id == deletion.id,
                    deletion_requests.c.claim_token == deletion.claim_token,
                )
                .values(
                    state="failed",
                    claim_token=None,
                    lease_expires_at=None,
                    failure_category="object_storage",
                    failure_message=message,
                    failed_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(deletion_outbox)
                .where(deletion_outbox.c.deletion_id == deletion.id)
                .values(
                    delivered_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=now,
                    last_error=message,
                    updated_at=now,
                )
            )
            self._insert_terminal_audit(connection, record, event_type="failed", now=now)

    def retry_database_cleanup(
        self, deletion: AgreementDeletion, *, message: str, next_retry_at: datetime
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            if not self._claim_is_current(connection, deletion, lock=True):
                return
            connection.execute(
                update(deletion_requests)
                .where(
                    deletion_requests.c.id == deletion.id,
                    deletion_requests.c.claim_token == deletion.claim_token,
                )
                .values(
                    state="retrying",
                    claim_token=None,
                    lease_expires_at=None,
                    next_attempt_at=next_retry_at,
                    failure_category="database_cleanup",
                    failure_message=message,
                    updated_at=now,
                )
            )
            connection.execute(
                update(deletion_outbox)
                .where(deletion_outbox.c.deletion_id == deletion.id)
                .values(
                    delivered_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=next_retry_at,
                    last_error=message,
                    updated_at=now,
                )
            )

    def fail_database_cleanup(self, deletion: AgreementDeletion, *, message: str) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            record = self._locked_claim(connection, deletion)
            if record is None:
                return
            connection.execute(
                update(deletion_requests)
                .where(
                    deletion_requests.c.id == deletion.id,
                    deletion_requests.c.claim_token == deletion.claim_token,
                )
                .values(
                    state="failed",
                    claim_token=None,
                    lease_expires_at=None,
                    failure_category="database_cleanup",
                    failure_message=message,
                    failed_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(deletion_outbox)
                .where(deletion_outbox.c.deletion_id == deletion.id)
                .values(
                    delivered_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=now,
                    last_error=message,
                    updated_at=now,
                )
            )
            self._insert_terminal_audit(connection, record, event_type="failed", now=now)

    def recover_stale_deletions(self, organization_id: UUID) -> int:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id)
            stale_ids = list(
                connection.scalars(
                    select(deletion_requests.c.id)
                    .where(
                        deletion_requests.c.organization_id == organization_id,
                        deletion_requests.c.state == "processing",
                        deletion_requests.c.lease_expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            if not stale_ids:
                return 0
            connection.execute(
                update(deletion_requests)
                .where(deletion_requests.c.id.in_(stale_ids))
                .values(
                    state="retrying",
                    claim_token=None,
                    lease_expires_at=None,
                    next_attempt_at=now,
                    failure_category="database_cleanup",
                    failure_message="Expired deletion lease recovered",
                    updated_at=now,
                )
            )
            connection.execute(
                update(deletion_outbox)
                .where(deletion_outbox.c.deletion_id.in_(stale_ids))
                .values(
                    delivered_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=now,
                    last_error="Expired deletion lease recovered",
                    updated_at=now,
                )
            )
            return len(stale_ids)

    def complete_and_purge(self, deletion: AgreementDeletion) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, deletion.organization_id)
            connection.execute(
                text(
                    """
                    SELECT id FROM agreements
                    WHERE id=:agreement_id
                      AND organization_id=:organization_id
                      AND workspace_id=:workspace_id
                    FOR UPDATE
                    """
                ),
                {
                    "agreement_id": deletion.agreement_id,
                    "organization_id": deletion.organization_id,
                    "workspace_id": deletion.workspace_id,
                },
            ).one()
            record = self._locked_claim(connection, deletion)
            if record is None:
                return
            pending = connection.scalar(
                select(deletion_objects.c.id)
                .where(
                    deletion_objects.c.deletion_id == deletion.id,
                    deletion_objects.c.state == "pending",
                )
                .limit(1)
            )
            if pending is not None:
                raise RuntimeError("agreement deletion inventory is not complete")
            unresolved_intent = connection.scalar(
                text(
                    """
                    SELECT intent.id
                    FROM processing_artifact_intents AS intent
                    LEFT JOIN agreement_deletion_objects AS object
                      ON object.deletion_id=:deletion_id
                     AND object.category=intent.category
                     AND object.object_key=intent.artifact_key
                    WHERE intent.agreement_id=:agreement_id
                      AND intent.organization_id=:organization_id
                      AND intent.workspace_id=:workspace_id
                      AND (
                          intent.state='expected'
                          OR object.id IS NULL
                          OR object.state NOT IN ('deleted', 'preserved')
                      )
                    LIMIT 1
                    """
                ),
                {
                    "deletion_id": deletion.id,
                    "agreement_id": deletion.agreement_id,
                    "organization_id": deletion.organization_id,
                    "workspace_id": deletion.workspace_id,
                },
            )
            if unresolved_intent is not None:
                raise RuntimeError("processing artifact intent is not reconciled")
            self._purge_owned_rows(connection, deletion)
            connection.execute(
                update(deletion_requests)
                .where(
                    deletion_requests.c.id == deletion.id,
                    deletion_requests.c.claim_token == deletion.claim_token,
                )
                .values(
                    state="completed",
                    title="Deleted agreement",
                    agreement_type="deleted",
                    file_checksums=[],
                    claim_token=None,
                    lease_expires_at=None,
                    failure_category=None,
                    failure_message=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            self._insert_terminal_audit(connection, record, event_type="completed", now=now)

    def organization_ids(self) -> list[UUID]:
        with self._engine.connect() as connection:
            return list(connection.scalars(text("SELECT id FROM organizations ORDER BY id")))

    def claim_due_outbox(self, organization_id: UUID) -> ClaimedDeletionOutbox | None:
        now = datetime.now(UTC)
        token = uuid4()
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id)
            record = (
                connection.execute(
                    select(deletion_outbox)
                    .join(
                        deletion_requests, deletion_outbox.c.deletion_id == deletion_requests.c.id
                    )
                    .where(
                        deletion_outbox.c.organization_id == organization_id,
                        deletion_outbox.c.delivered_at.is_(None),
                        deletion_outbox.c.next_attempt_at <= now,
                        deletion_requests.c.state.in_(("accepted", "retrying")),
                    )
                    .where(
                        or_(
                            deletion_outbox.c.lease_token.is_(None),
                            deletion_outbox.c.lease_expires_at <= now,
                        )
                    )
                    .order_by(deletion_outbox.c.next_attempt_at, deletion_outbox.c.id)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .first()
            )
            if record is None:
                return None
            connection.execute(
                update(deletion_outbox)
                .where(deletion_outbox.c.id == record["id"])
                .values(
                    lease_token=token,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                    attempt_count=deletion_outbox.c.attempt_count + 1,
                    updated_at=now,
                )
            )
            return ClaimedDeletionOutbox(
                id=cast(UUID, record["id"]),
                deletion_id=cast(UUID, record["deletion_id"]),
                agreement_id=cast(UUID, record["agreement_id"]),
                organization_id=cast(UUID, record["organization_id"]),
                workspace_id=cast(UUID, record["workspace_id"]),
                lease_token=token,
                attempt_count=int(record["attempt_count"]) + 1,
            )

    def mark_outbox_delivered(self, message: ClaimedDeletionOutbox) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, message.organization_id)
            connection.execute(
                update(deletion_outbox)
                .where(
                    deletion_outbox.c.id == message.id,
                    deletion_outbox.c.lease_token == message.lease_token,
                    deletion_outbox.c.delivered_at.is_(None),
                )
                .values(
                    delivered_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    last_error=None,
                    updated_at=now,
                )
            )

    def release_outbox(self, message: ClaimedDeletionOutbox, *, next_attempt_at: datetime) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, message.organization_id)
            connection.execute(
                update(deletion_outbox)
                .where(
                    deletion_outbox.c.id == message.id,
                    deletion_outbox.c.lease_token == message.lease_token,
                    deletion_outbox.c.delivered_at.is_(None),
                )
                .values(
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=next_attempt_at,
                    last_error="Agreement deletion outbox delivery failed",
                    updated_at=now,
                )
            )

    def _finish_object(
        self,
        connection: Any,
        deletion: AgreementDeletion,
        object_id: UUID,
        *,
        state: str,
        now: datetime,
    ) -> None:
        connection.execute(
            update(deletion_objects)
            .where(
                deletion_objects.c.id == object_id,
                deletion_objects.c.deletion_id == deletion.id,
                deletion_objects.c.state == "pending",
            )
            .values(state=state, last_error=None, updated_at=now)
        )
        connection.execute(
            update(deletion_requests)
            .where(
                deletion_requests.c.id == deletion.id,
                deletion_requests.c.claim_token == deletion.claim_token,
            )
            .values(lease_expires_at=now + timedelta(seconds=self._lease_seconds), updated_at=now)
        )

    def _locked_claim(self, connection: Any, deletion: AgreementDeletion) -> Any | None:
        return (
            connection.execute(
                select(deletion_requests)
                .where(
                    deletion_requests.c.id == deletion.id,
                    deletion_requests.c.organization_id == deletion.organization_id,
                    deletion_requests.c.workspace_id == deletion.workspace_id,
                    deletion_requests.c.state == "processing",
                    deletion_requests.c.claim_token == deletion.claim_token,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )

    def _claim_is_current(
        self, connection: Any, deletion: AgreementDeletion, *, lock: bool
    ) -> bool:
        statement = select(deletion_requests.c.id).where(
            deletion_requests.c.id == deletion.id,
            deletion_requests.c.organization_id == deletion.organization_id,
            deletion_requests.c.workspace_id == deletion.workspace_id,
            deletion_requests.c.state == "processing",
            deletion_requests.c.claim_token == deletion.claim_token,
        )
        if lock:
            statement = statement.with_for_update()
        return connection.scalar(statement) is not None

    @staticmethod
    def _lock_object_key(connection: Any, object_key: str) -> None:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:object_key, 0))"),
                {"object_key": object_key},
            )

    @staticmethod
    def _insert_terminal_audit(
        connection: Any, record: Any, *, event_type: str, now: datetime
    ) -> None:
        connection.execute(
            insert(deletion_audit_events).values(
                id=uuid4(),
                organization_id=record["organization_id"],
                workspace_id=record["workspace_id"],
                agreement_id=record["agreement_id"],
                title=record["title"],
                agreement_type=record["agreement_type"],
                file_checksums=record["file_checksums"],
                actor_id=record["actor_id"],
                deletion_id=record["id"],
                event_type=event_type,
                retry_cycle=record["retry_cycle"],
                metadata_json={"attempt_count": record["attempt_count"]},
                occurred_at=now,
            )
        )

    @staticmethod
    def _purge_owned_rows(connection: Any, deletion: AgreementDeletion) -> None:
        # Immutable review decisions have a database-enforced FK to findings, and
        # those findings reach the agreement through evaluations. Keep only that
        # legal/audit identity chain, scrub its mutable evidence payload, and keep
        # the agreement itself as a non-readable tombstone. Every other derived
        # row is physically removed below in FK-safe order.
        values = {
            "agreement_id": deletion.agreement_id,
            "organization_id": deletion.organization_id,
            "workspace_id": deletion.workspace_id,
            "deletion_id": deletion.id,
        }
        review_ids = "SELECT id FROM review_cases WHERE agreement_id=:agreement_id"
        workflow_ids = f"SELECT id FROM review_workflows WHERE review_id IN ({review_ids})"
        statements = (
            """
            DELETE FROM question_turns WHERE thread_id IN (
                SELECT id FROM question_threads
                WHERE organization_id=:organization_id
                  AND workspace_id=:workspace_id
                  AND CAST(agreement_ids AS jsonb)
                      @> jsonb_build_array(CAST(:agreement_id AS text))
            )
            """,
            """
            DELETE FROM question_threads
            WHERE organization_id=:organization_id
              AND workspace_id=:workspace_id
              AND CAST(agreement_ids AS jsonb)
                  @> jsonb_build_array(CAST(:agreement_id AS text))
            """,
            f"DELETE FROM review_final_packages WHERE review_id IN ({review_ids})",
            f"DELETE FROM review_notification_events WHERE review_id IN ({review_ids})",
            f"DELETE FROM review_workflow_outbox WHERE workflow_id IN ({workflow_ids})",
            f"DELETE FROM review_workflow_decisions WHERE workflow_id IN ({workflow_ids})",
            f"DELETE FROM review_workflow_stages WHERE workflow_id IN ({workflow_ids})",
            f"DELETE FROM review_workflows WHERE review_id IN ({review_ids})",
            f"DELETE FROM review_assignments WHERE review_id IN ({review_ids})",
            f"DELETE FROM review_comments WHERE review_id IN ({review_ids})",
            "DELETE FROM review_cases WHERE agreement_id=:agreement_id",
            "DELETE FROM version_comparison_changes WHERE agreement_id=:agreement_id",
            "DELETE FROM version_comparison_runs WHERE agreement_id=:agreement_id",
            "DELETE FROM retrieval_chunk_embeddings WHERE agreement_id=:agreement_id",
            "DELETE FROM retrieval_chunks WHERE agreement_id=:agreement_id",
            "DELETE FROM retrieval_index_builds WHERE agreement_id=:agreement_id",
            """
            UPDATE playbook_evaluations
            SET processing_job_id=NULL, requested_by=NULL,
                analysis_version='deleted', extraction_version='deleted', state='deleted'
            WHERE agreement_id=:agreement_id
            """,
            """
            DELETE FROM playbook_findings
            WHERE evaluation_id IN (
                SELECT id FROM playbook_evaluations WHERE agreement_id=:agreement_id
            ) AND NOT EXISTS (
                SELECT 1 FROM review_decisions
                WHERE review_decisions.finding_id=playbook_findings.id
            )
            """,
            """
            UPDATE playbook_findings
            SET citation_ids='[]'::json, risk_payload='{}'::json,
                fallback_suggestions='[]'::json, extraction_version='deleted'
            WHERE evaluation_id IN (
                SELECT id FROM playbook_evaluations WHERE agreement_id=:agreement_id
            )
            """,
            """
            DELETE FROM playbook_evaluations
            WHERE agreement_id=:agreement_id AND NOT EXISTS (
                SELECT 1 FROM playbook_findings
                WHERE playbook_findings.evaluation_id=playbook_evaluations.id
            )
            """,
            "DELETE FROM processing_outbox WHERE agreement_id=:agreement_id",
            "DELETE FROM processing_artifacts WHERE agreement_id=:agreement_id",
            "DELETE FROM processing_artifact_intents WHERE agreement_id=:agreement_id",
            "DELETE FROM processing_jobs WHERE agreement_id=:agreement_id",
            "DELETE FROM agreement_versions WHERE agreement_id=:agreement_id",
            "DELETE FROM agreement_deletion_objects WHERE deletion_id=:deletion_id",
            "DELETE FROM agreement_deletion_outbox WHERE deletion_id=:deletion_id",
        )
        for statement in statements:
            connection.execute(text(statement), values)
        tombstone = connection.execute(
            text(
                """
                UPDATE agreements
                SET title='Deleted agreement', agreement_type='deleted', status='deleted',
                    parties='[]'::json, files='[]'::json, processing_state='deleted',
                    audit_metadata='{}'::json, audit_events='[]'::json,
                    current_version_id=NULL, comparison_baseline_version_id=NULL,
                    archived_at=NULL, updated_at=now()
                WHERE id=:agreement_id AND organization_id=:organization_id
                  AND workspace_id=:workspace_id AND deletion_requested_at IS NOT NULL
                """
            ),
            values,
        )
        if tombstone.rowcount != 1:
            raise RuntimeError("agreement deletion tombstone is missing")


def _validate_owned_key(deletion: AgreementDeletion, item: AgreementDeletionObject) -> None:
    parts = item.object_key.split("/")
    organization_id, workspace_id, agreement_id = (
        str(deletion.organization_id),
        str(deletion.workspace_id),
        str(deletion.agreement_id),
    )
    valid = False
    if item.category == "source":
        valid = (
            len(parts) == 7
            and parts[:5] == ["tenants", organization_id, "workspaces", workspace_id, "documents"]
            and _is_sha256(parts[5])
            and parts[6] in {"original.pdf", "original.docx"}
        )
    elif item.category == "analysis":
        valid = (
            len(parts) == 9
            and parts[:7]
            == [
                "tenants",
                organization_id,
                "workspaces",
                workspace_id,
                "agreements",
                agreement_id,
                "analysis",
            ]
            and _is_sha256(parts[7])
            and parts[8] == "document-analysis.v1.json"
        )
    elif item.category == "comparison":
        valid = (
            len(parts) == 3
            and parts[0] == "comparisons"
            and _is_uuid(parts[1])
            and parts[2] == "version-comparison.v1.json"
        )
    elif item.category in {"review_manifest", "review_pdf"}:
        expected_file = "manifest.json" if item.category == "review_manifest" else "report.pdf"
        valid = (
            len(parts) == 6
            and parts[:3] == ["reviews", organization_id, workspace_id]
            and _is_uuid(parts[3])
            and parts[4:] == ["final-package", expected_file]
        )
    if not valid:
        raise ObjectCleanupError("deletion object key does not match its owned category")


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _set_tenant_context(connection: Any, organization_id: UUID) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
