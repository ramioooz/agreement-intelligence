from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from agreement_intelligence_worker import review_workflow
from agreement_intelligence_worker.review_workflow import (
    PostgresWorkflowCheckpointStore,
    SQLAlchemyWorkflowEventProcessor,
    _workflow_event_for_update,
    workflow_events,
    workflow_metadata,
    workflows,
)
from sqlalchemy import create_engine, insert, select
from sqlalchemy.dialects import postgresql


def test_workflow_event_delivery_locks_the_outbox_row_before_checkpointing() -> None:
    statement = _workflow_event_for_update(uuid4())

    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]

    assert "FOR UPDATE OF review_workflow_outbox" in sql


def test_postgres_checkpoint_schema_is_initialized_before_event_processing(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    class FakeCheckpointer:
        def setup(self) -> None:
            calls.append("setup")

    @contextmanager
    def saver_factory(database_url: str) -> Any:
        assert database_url == "postgresql://worker"
        yield FakeCheckpointer()

    store = PostgresWorkflowCheckpointStore(
        "postgresql://worker",
        saver_factory=saver_factory,
    )

    assert calls == ["setup"]

    class Snapshot:
        def __init__(self, values: dict[str, object]) -> None:
            self.values = values

    states: dict[str, dict[str, object]] = {}

    class FakeGraph:
        def get_state(self, config: dict[str, dict[str, str]]) -> Snapshot:
            namespace = config["configurable"]["checkpoint_ns"]
            return Snapshot(states.get(namespace, {}))

        def invoke(self, state: dict[str, object], *, config: dict[str, dict[str, str]]) -> None:
            calls.append("invoke")
            states[config["configurable"]["checkpoint_ns"]] = state

    monkeypatch.setattr(
        review_workflow,
        "_compiled_checkpoint_graph",
        lambda checkpointer: FakeGraph(),
    )

    event_id = uuid4()
    store.persist(
        event_id=event_id,
        checkpoint_id=uuid4(),
        workflow_id=uuid4(),
        event_type="review.workflow.resume",
    )
    store.persist(
        event_id=event_id,
        checkpoint_id=uuid4(),
        workflow_id=uuid4(),
        event_type="review.workflow.resume",
    )

    assert calls == ["setup", "invoke"]


class RecordingCheckpointStore:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object, object]] = []

    def persist(
        self,
        *,
        event_id: object,
        checkpoint_id: object,
        workflow_id: object,
        event_type: object,
    ) -> None:
        self.calls.append((event_id, checkpoint_id, workflow_id, event_type))


def test_workflow_event_is_checkpointed_once_even_when_delivery_is_repeated() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    workflow_metadata.create_all(engine)
    workflow_id, event_id, checkpoint_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(insert(workflows).values(id=workflow_id, checkpoint_id=checkpoint_id))
        connection.execute(
            insert(workflow_events).values(
                id=event_id,
                workflow_id=workflow_id,
                event_type="review.workflow.resume",
                processed_at=None,
            )
        )
    checkpoints = RecordingCheckpointStore()
    processor = SQLAlchemyWorkflowEventProcessor(engine, checkpoints)

    assert processor.process(event_id) is True
    assert processor.process(event_id) is False
    assert checkpoints.calls == [(event_id, checkpoint_id, workflow_id, "review.workflow.resume")]
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(workflow_events.c.processed_at).where(workflow_events.c.id == event_id)
            )
            is not None
        )
    engine.dispose()
