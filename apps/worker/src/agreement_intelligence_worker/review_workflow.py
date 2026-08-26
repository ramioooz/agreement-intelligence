"""Idempotently persist review-workflow wake-ups as LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict, cast
from uuid import UUID

from agreement_intelligence_platform.observability import record_metric, safe_span_attributes
from agreement_intelligence_platform.telemetry import operation_span
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.sql import Select

logger = logging.getLogger("agreement_intelligence.worker")


class GraphState(TypedDict):
    event_id: str
    workflow_id: str
    event_type: str


workflow_metadata = MetaData()
workflow_events = Table(
    "review_workflow_outbox",
    workflow_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("workflow_id", Uuid(as_uuid=True), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=True),
)
workflows = Table(
    "review_workflows",
    workflow_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("review_id", Uuid(as_uuid=True), nullable=False),
    Column("checkpoint_id", Uuid(as_uuid=True), nullable=False),
)
reviews = Table(
    "review_cases",
    workflow_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
)
agreements = Table(
    "agreements",
    workflow_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("deletion_requested_at", DateTime(timezone=True), nullable=True),
)


@dataclass(frozen=True)
class WorkflowMessage:
    event_id: UUID
    receipt_handle: str
    organization_id: UUID
    workspace_id: UUID


class WorkflowMessageReceiver(Protocol):
    async def receive(self) -> WorkflowMessage | None: ...

    async def ack(self, message: WorkflowMessage) -> None: ...


class WorkflowCheckpointStore(Protocol):
    def persist(
        self,
        *,
        event_id: UUID,
        checkpoint_id: UUID,
        workflow_id: UUID,
        event_type: str,
    ) -> None: ...


class SQSWorkflowMessageReceiver:
    def __init__(self, *, client: Any, queue_url: str, wait_time_seconds: int = 10) -> None:
        self._client = client
        self._queue_url = queue_url
        self._wait_time_seconds = wait_time_seconds

    async def receive(self) -> WorkflowMessage | None:
        result = await asyncio.to_thread(
            self._client.receive_message,
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=self._wait_time_seconds,
        )
        messages = result.get("Messages", [])
        if not messages:
            return None
        message = messages[0]
        body = json.loads(str(message["Body"]))
        if body.get("kind") != "review-workflow":
            return None
        return WorkflowMessage(
            event_id=UUID(str(body["event_id"])),
            receipt_handle=str(message["ReceiptHandle"]),
            organization_id=UUID(str(body["organization_id"])),
            workspace_id=UUID(str(body["workspace_id"])),
        )

    async def ack(self, message: WorkflowMessage) -> None:
        await asyncio.to_thread(
            self._client.delete_message,
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
        )


class PostgresWorkflowCheckpointStore:
    def __init__(
        self,
        database_url: str,
        *,
        saver_factory: Callable[[str], AbstractContextManager[Any]] | None = None,
    ) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._saver_factory = saver_factory or (
            lambda connection_string: PostgresSaver.from_conn_string(connection_string)
        )
        with self._saver_factory(self._database_url) as checkpointer:
            checkpointer.setup()

    def persist(
        self,
        *,
        event_id: UUID,
        checkpoint_id: UUID,
        workflow_id: UUID,
        event_type: str,
    ) -> None:
        config = {
            "configurable": {
                # Each durable outbox event is its own top-level checkpoint thread.
                # LangGraph reserves checkpoint namespaces for compiled subgraphs.
                "thread_id": f"review-workflow-event:{event_id}",
            }
        }
        with self._saver_factory(self._database_url) as checkpointer:
            graph = _compiled_checkpoint_graph(checkpointer)
            if graph.get_state(config).values:
                return
            graph.invoke(
                {
                    "event_id": str(event_id),
                    "workflow_id": str(workflow_id),
                    "event_type": event_type,
                },
                config=config,
            )


def _compiled_checkpoint_graph(checkpointer: Any) -> Any:
    graph = StateGraph(GraphState)
    graph.add_node("checkpoint", lambda state: state)
    graph.add_edge(START, "checkpoint")
    return graph.compile(checkpointer=checkpointer)


class SQLAlchemyWorkflowEventProcessor:
    def __init__(self, engine: Engine, checkpoints: WorkflowCheckpointStore) -> None:
        self._engine = engine
        self._checkpoints = checkpoints

    def process(self, event_id: UUID, *, organization_id: UUID, workspace_id: UUID) -> bool:
        transition_outcome = "success"
        processed = False
        try:
            with operation_span(
                "agreement-intelligence.worker",
                "workflow.transition",
                safe_span_attributes(
                    {"operation": "workflow.transition", "outcome": transition_outcome}
                ),
                outcome_getter=lambda: transition_outcome,
            ) as span:
                with self._engine.begin() as connection:
                    _set_tenant_context(connection, organization_id)
                    row = (
                        connection.execute(_workflow_event_for_update(event_id))
                        .mappings()
                        .one_or_none()
                    )
                    if (
                        row is None
                        or row["processed_at"] is not None
                        or row["organization_id"] != organization_id
                        or row["workspace_id"] != workspace_id
                    ):
                        transition_outcome = "skipped"
                    else:
                        self._checkpoints.persist(
                            event_id=event_id,
                            checkpoint_id=row["checkpoint_id"],
                            workflow_id=row["workflow_id"],
                            event_type=row["event_type"],
                        )
                        connection.execute(
                            update(workflow_events)
                            .where(workflow_events.c.id == event_id)
                            .where(workflow_events.c.processed_at.is_(None))
                            .values(processed_at=func.now())
                        )
                        processed = True
                span.set_attributes(
                    cast(
                        Any,
                        safe_span_attributes(
                            {"workflow_state": "processed" if processed else "skipped"}
                        ),
                    )
                )
        except Exception:
            record_metric(
                "agreement_intelligence.workflow.transition_count",
                1,
                operation="workflow.transition",
                outcome="failure",
            )
            raise
        record_metric(
            "agreement_intelligence.workflow.transition_count",
            1,
            operation="workflow.transition",
            outcome=transition_outcome,
        )
        return processed


def _workflow_event_for_update(event_id: UUID) -> Select[Any]:
    return (
        select(workflow_events, workflows.c.checkpoint_id)
        .join(workflows, workflows.c.id == workflow_events.c.workflow_id)
        .join(reviews, reviews.c.id == workflows.c.review_id)
        .join(agreements, agreements.c.id == reviews.c.agreement_id)
        .where(workflow_events.c.id == event_id)
        .where(agreements.c.deletion_requested_at.is_(None))
        .with_for_update(of=workflow_events)
    )


async def run_workflow_loop(
    stop_event: asyncio.Event,
    receiver: WorkflowMessageReceiver,
    processor: SQLAlchemyWorkflowEventProcessor,
) -> None:
    while not stop_event.is_set():
        message = await receiver.receive()
        if message is None:
            continue
        try:
            processor.process(
                message.event_id,
                organization_id=message.organization_id,
                workspace_id=message.workspace_id,
            )
        except Exception:
            logger.exception("review workflow message handling failed")
            continue
        await receiver.ack(message)


def _set_tenant_context(connection: Any, organization_id: UUID) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
