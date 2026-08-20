"""Idempotently persist review-workflow wake-ups as LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.sql import Select


class GraphState(TypedDict):
    event_id: str
    workflow_id: str
    event_type: str


workflow_metadata = MetaData()
workflow_events = Table(
    "review_workflow_outbox",
    workflow_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("workflow_id", Uuid(as_uuid=True), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=True),
)
workflows = Table(
    "review_workflows",
    workflow_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("checkpoint_id", Uuid(as_uuid=True), nullable=False),
)


@dataclass(frozen=True)
class WorkflowMessage:
    event_id: UUID
    receipt_handle: str


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
            event_id=UUID(str(body["event_id"])), receipt_handle=str(message["ReceiptHandle"])
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
                "thread_id": str(checkpoint_id),
                "checkpoint_ns": f"event:{event_id}",
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

    def process(self, event_id: UUID) -> bool:
        with self._engine.begin() as connection:
            row = connection.execute(_workflow_event_for_update(event_id)).mappings().one_or_none()
            if row is None or row["processed_at"] is not None:
                return False
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
        return True


def _workflow_event_for_update(event_id: UUID) -> Select[Any]:
    return (
        select(workflow_events, workflows.c.checkpoint_id)
        .join(workflows, workflows.c.id == workflow_events.c.workflow_id)
        .where(workflow_events.c.id == event_id)
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
        processor.process(message.event_id)
        await receiver.ack(message)
