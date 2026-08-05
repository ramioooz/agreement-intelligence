from uuid import uuid4

from agreement_intelligence_worker.review_workflow import (
    SQLAlchemyWorkflowEventProcessor,
    workflow_events,
    workflow_metadata,
    workflows,
)
from sqlalchemy import create_engine, insert, select


class RecordingCheckpointStore:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object]] = []

    def persist(self, *, checkpoint_id: object, workflow_id: object, event_type: object) -> None:
        self.calls.append((checkpoint_id, workflow_id, event_type))


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
    assert checkpoints.calls == [(checkpoint_id, workflow_id, "review.workflow.resume")]
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(workflow_events.c.processed_at).where(workflow_events.c.id == event_id)
            )
            is not None
        )
    engine.dispose()
