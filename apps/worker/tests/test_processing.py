import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    JobProcessor,
    ProcessingJob,
    ProcessingMessage,
    RetryPolicy,
    SQLAlchemyProcessingJobRepository,
    SQSProcessingQueue,
    TransientProcessingError,
    create_processing_tables,
    run_processing_loop,
)
from sqlalchemy import create_engine, select


@dataclass
class InMemoryRepository:
    job: ProcessingJob
    artifacts: list[CompletedArtifact]

    def claim(self, job_id: UUID) -> ProcessingJob | None:
        if self.job.id != job_id or self.job.state != "queued":
            return None
        self.job = replace(
            self.job,
            state="processing",
            attempt_count=self.job.attempt_count + 1,
            processing_started_at=datetime.now(UTC),
        )
        return self.job

    def complete(self, job_id: UUID, artifact: CompletedArtifact) -> None:
        if self.job.id != job_id:
            raise LookupError(job_id)
        if self.job.state == "completed":
            return
        self.artifacts.append(artifact)
        self.job = replace(self.job, state="completed", completed_at=datetime.now(UTC))

    def requeue(
        self, job_id: UUID, *, category: str, message: str, next_retry_at: datetime
    ) -> None:
        assert self.job.id == job_id
        self.job = replace(
            self.job,
            state="queued",
            failure_category=category,
            failure_message=message,
            next_retry_at=next_retry_at,
        )

    def fail(self, job_id: UUID, *, category: str, message: str) -> None:
        assert self.job.id == job_id
        self.job = replace(
            self.job, state="failed", failure_category=category, failure_message=message
        )


@dataclass
class InMemoryQueue:
    retries: list[tuple[UUID, int]]

    def enqueue(self, job_id: UUID, *, delay_seconds: int) -> None:
        self.retries.append((job_id, delay_seconds))


class PlaceholderProcessor:
    def process(self, job: ProcessingJob) -> CompletedArtifact:
        return CompletedArtifact(job_id=job.id, key=f"checkpoints/{job.id}/placeholder.json")


class FlakyProcessor:
    def process(self, job: ProcessingJob) -> CompletedArtifact:
        raise TransientProcessingError("Temporary provider failure")


def _job() -> ProcessingJob:
    return ProcessingJob(id=uuid4(), agreement_id=uuid4(), state="queued", attempt_count=0)


def test_duplicate_delivery_does_not_duplicate_completed_artifacts() -> None:
    repository = InMemoryRepository(job=_job(), artifacts=[])
    queue = InMemoryQueue(retries=[])
    worker = JobProcessor(repository, queue, PlaceholderProcessor())

    worker.handle(repository.job.id)
    worker.handle(repository.job.id)

    assert repository.job.state == "completed"
    assert [artifact.key for artifact in repository.artifacts] == [
        f"checkpoints/{repository.job.id}/placeholder.json"
    ]
    assert queue.retries == []


def test_processing_loop_consumes_and_acknowledges_fake_messages() -> None:
    class OneMessageReceiver:
        def __init__(self, job_id: UUID) -> None:
            self._messages = [ProcessingMessage(job_id=job_id, receipt_handle="receipt-1")]
            self.acked: list[str] = []

        async def receive(self) -> ProcessingMessage | None:
            if self._messages:
                return self._messages.pop(0)
            stop_event.set()
            return None

        async def ack(self, message: ProcessingMessage) -> None:
            self.acked.append(message.receipt_handle)

    repository = InMemoryRepository(job=_job(), artifacts=[])
    receiver = OneMessageReceiver(repository.job.id)
    stop_event = asyncio.Event()
    worker = JobProcessor(repository, InMemoryQueue(retries=[]), PlaceholderProcessor())

    asyncio.run(
        run_processing_loop(
            stop_event,
            receiver=receiver,
            processor=worker,
            idle_sleep_seconds=0,
        )
    )

    assert repository.job.state == "completed"
    assert receiver.acked == ["receipt-1"]


def test_redelivery_repairs_processing_job_when_artifact_already_exists(tmp_path: Path) -> None:
    from agreement_intelligence_worker.processing import processing_artifacts, processing_jobs

    class OneMessageReceiver:
        def __init__(self, job_id: UUID) -> None:
            self._messages = [ProcessingMessage(job_id=job_id, receipt_handle="receipt-1")]
            self.acked: list[str] = []

        async def receive(self) -> ProcessingMessage | None:
            if self._messages:
                return self._messages.pop(0)
            stop_event.set()
            return None

        async def ack(self, message: ProcessingMessage) -> None:
            self.acked.append(message.receipt_handle)

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'processing.db'}")
    create_processing_tables(engine)
    job_id = uuid4()
    agreement_id = uuid4()
    now = datetime.now(UTC)
    artifact_key = f"checkpoints/{job_id}/placeholder.json"
    with engine.begin() as connection:
        connection.execute(
            processing_jobs.insert().values(
                id=job_id,
                organization_id=uuid4(),
                workspace_id=uuid4(),
                agreement_id=agreement_id,
                idempotency_key="processing-v1",
                profile="baseline",
                state="processing",
                attempt_count=1,
                failure_category=None,
                failure_message=None,
                next_retry_at=None,
                queued_at=now,
                processing_started_at=now,
                completed_at=None,
                failed_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            processing_artifacts.insert().values(
                id=uuid4(),
                job_id=job_id,
                agreement_id=agreement_id,
                artifact_key=artifact_key,
                created_at=now,
            )
        )

    receiver = OneMessageReceiver(job_id)
    stop_event = asyncio.Event()
    repository = SQLAlchemyProcessingJobRepository(engine)
    worker = JobProcessor(repository, InMemoryQueue(retries=[]), PlaceholderProcessor())

    asyncio.run(
        run_processing_loop(
            stop_event,
            receiver=receiver,
            processor=worker,
            idle_sleep_seconds=0,
        )
    )

    with engine.connect() as connection:
        repaired = connection.execute(
            select(
                processing_jobs.c.state,
                processing_jobs.c.completed_at,
                processing_jobs.c.processing_started_at,
            ).where(processing_jobs.c.id == job_id)
        ).one()
        artifact_count = len(
            connection.execute(
                select(processing_artifacts.c.id).where(processing_artifacts.c.job_id == job_id)
            ).all()
        )

    assert repaired.state == "completed"
    assert repaired.completed_at is not None
    assert repaired.processing_started_at is not None
    assert artifact_count == 1
    assert receiver.acked == ["receipt-1"]


def test_redelivery_reprocesses_processing_job_without_artifact(tmp_path: Path) -> None:
    from agreement_intelligence_worker.processing import processing_artifacts, processing_jobs

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'processing.db'}")
    create_processing_tables(engine)
    job_id = uuid4()
    agreement_id = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            processing_jobs.insert().values(
                id=job_id,
                organization_id=uuid4(),
                workspace_id=uuid4(),
                agreement_id=agreement_id,
                idempotency_key="processing-v1",
                profile="baseline",
                state="processing",
                attempt_count=1,
                failure_category=None,
                failure_message=None,
                next_retry_at=None,
                queued_at=now,
                processing_started_at=now,
                completed_at=None,
                failed_at=None,
                created_at=now,
                updated_at=now,
            )
        )

    repository = SQLAlchemyProcessingJobRepository(engine)
    worker = JobProcessor(repository, InMemoryQueue(retries=[]), PlaceholderProcessor())

    worker.handle(job_id)

    with engine.connect() as connection:
        completed = connection.execute(
            select(processing_jobs.c.state, processing_jobs.c.completed_at).where(
                processing_jobs.c.id == job_id
            )
        ).one()
        artifacts = connection.execute(
            select(processing_artifacts.c.artifact_key).where(
                processing_artifacts.c.job_id == job_id
            )
        ).all()

    assert completed.state == "completed"
    assert completed.completed_at is not None
    assert [artifact.artifact_key for artifact in artifacts] == [
        f"checkpoints/{job_id}/placeholder.json"
    ]


def test_sqs_retry_queue_omits_fifo_fields_for_standard_queue() -> None:
    class RecordingSQSClient:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        def send_message(self, **request: object) -> None:
            self.messages.append(request)

    client = RecordingSQSClient()
    job_id = uuid4()

    SQSProcessingQueue(client=client, queue_url="https://sqs.example/processing").enqueue(
        job_id, delay_seconds=2
    )

    assert client.messages == [
        {
            "QueueUrl": "https://sqs.example/processing",
            "MessageBody": json.dumps({"job_id": str(job_id)}, sort_keys=True),
            "DelaySeconds": 2,
        }
    ]


def test_sqs_retry_queue_uses_fifo_fields_for_fifo_queue() -> None:
    class RecordingSQSClient:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        def send_message(self, **request: object) -> None:
            self.messages.append(request)

    client = RecordingSQSClient()
    job_id = uuid4()

    SQSProcessingQueue(client=client, queue_url="https://sqs.example/processing.fifo").enqueue(
        job_id, delay_seconds=2
    )

    assert len(client.messages) == 1
    message = client.messages[0]
    assert message["QueueUrl"] == "https://sqs.example/processing.fifo"
    assert message["MessageBody"] == json.dumps({"job_id": str(job_id)}, sort_keys=True)
    assert message["DelaySeconds"] == 2
    assert message["MessageGroupId"] == str(job_id)
    assert str(message["MessageDeduplicationId"]).startswith(f"{job_id}:retry:2:")


def test_transient_failure_is_requeued_with_bounded_backoff_without_sleeping() -> None:
    repository = InMemoryRepository(job=_job(), artifacts=[])
    queue = InMemoryQueue(retries=[])
    worker = JobProcessor(
        repository,
        queue,
        FlakyProcessor(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=2, max_delay_seconds=5),
    )

    worker.handle(repository.job.id)

    assert repository.job.state == "queued"
    assert repository.job.attempt_count == 1
    assert repository.job.failure_category == "transient"
    assert repository.job.failure_message == "Temporary provider failure"
    assert repository.job.next_retry_at is not None
    assert queue.retries == [(repository.job.id, 2)]


def test_transient_failure_stops_after_the_configured_attempt_bound() -> None:
    job = replace(_job(), attempt_count=2)
    repository = InMemoryRepository(job=job, artifacts=[])
    queue = InMemoryQueue(retries=[])
    worker = JobProcessor(
        repository,
        queue,
        FlakyProcessor(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=2, max_delay_seconds=5),
    )

    worker.handle(job.id)

    assert repository.job.state == "failed"
    assert repository.job.attempt_count == 3
    assert repository.job.failure_category == "transient_exhausted"
    assert queue.retries == []
