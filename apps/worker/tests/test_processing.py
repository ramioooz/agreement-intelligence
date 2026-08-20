import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agreement_intelligence_worker.playbook_evaluation import (
    SQLAlchemyPlaybookEvaluationSink,
    worker_evaluation_metadata,
)
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
from pytest import LogCaptureFixture, raises
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

    def completed_artifact(self, job_id: UUID) -> tuple[ProcessingJob, CompletedArtifact] | None:
        if self.job.id != job_id or self.job.state != "completed" or not self.artifacts:
            return None
        return self.job, self.artifacts[-1]

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


def test_evaluation_recovery_runs_only_after_durable_completion() -> None:
    repository = InMemoryRepository(job=_job(), artifacts=[])
    queue = InMemoryQueue(retries=[])
    observed: list[tuple[str, UUID, str]] = []

    class EvaluationHandler:
        def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
            observed.append((repository.job.state, job.id, artifact.key))

    worker = JobProcessor(
        repository,
        queue,
        PlaceholderProcessor(),
        completion_handler=EvaluationHandler(),
    )

    worker.handle(repository.job.id)
    worker.handle(repository.job.id)

    assert observed == [
        ("completed", repository.job.id, f"checkpoints/{repository.job.id}/placeholder.json"),
        ("completed", repository.job.id, f"checkpoints/{repository.job.id}/placeholder.json"),
    ]


def test_completion_failure_does_not_run_evaluation_handler() -> None:
    class FailingRepository(InMemoryRepository):
        def complete(self, job_id: UUID, artifact: CompletedArtifact) -> None:
            raise RuntimeError("database completion failed")

    repository = FailingRepository(job=_job(), artifacts=[])
    observed: list[CompletedArtifact] = []

    class EvaluationHandler:
        def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
            observed.append(artifact)

    worker = JobProcessor(
        repository,
        InMemoryQueue(retries=[]),
        PlaceholderProcessor(),
        completion_handler=EvaluationHandler(),
    )

    with raises(RuntimeError, match="database completion failed"):
        worker.handle(repository.job.id)

    assert observed == []


def test_transient_completion_handler_failure_recovers_on_redelivery() -> None:
    repository = InMemoryRepository(job=_job(), artifacts=[])
    attempts: list[str] = []

    class FlakyEvaluationHandler:
        def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
            attempts.append(artifact.key)
            if len(attempts) == 1:
                raise RuntimeError("evaluation database temporarily unavailable")

    worker = JobProcessor(
        repository,
        InMemoryQueue(retries=[]),
        PlaceholderProcessor(),
        completion_handler=FlakyEvaluationHandler(),
    )

    with raises(RuntimeError, match="temporarily unavailable"):
        worker.handle(repository.job.id)
    worker.handle(repository.job.id)

    assert repository.job.state == "completed"
    assert attempts == [
        f"checkpoints/{repository.job.id}/placeholder.json",
        f"checkpoints/{repository.job.id}/placeholder.json",
    ]


def test_completing_a_version_job_updates_agreement_and_version_state(tmp_path: Path) -> None:
    from agreement_intelligence_worker.processing import (
        agreement_versions,
        agreements,
        processing_jobs,
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'processing.db'}")
    create_processing_tables(engine)
    job_id = uuid4()
    agreement_id = uuid4()
    version_id = uuid4()
    organization_id = uuid4()
    workspace_id = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            agreements.insert().values(
                id=agreement_id,
                organization_id=organization_id,
                current_version_id=version_id,
                processing_state="queued",
                updated_at=now,
            )
        )
        connection.execute(
            agreement_versions.insert().values(
                id=version_id,
                agreement_id=agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                processing_state="queued",
            )
        )
        connection.execute(
            processing_jobs.insert().values(
                id=job_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=agreement_id,
                version_id=version_id,
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

    SQLAlchemyProcessingJobRepository(engine).complete(
        job_id,
        CompletedArtifact(job_id=job_id, key=f"checkpoints/{job_id}/result.json"),
    )

    with engine.connect() as connection:
        agreement_state = connection.execute(
            select(agreements.c.processing_state).where(agreements.c.id == agreement_id),
        ).scalar_one()
        version_state = connection.execute(
            select(agreement_versions.c.processing_state).where(
                agreement_versions.c.id == version_id
            ),
        ).scalar_one()

    assert agreement_state == "completed"
    assert version_state == "completed"


def test_completing_a_deleted_job_is_a_safe_no_op(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'processing.db'}")
    create_processing_tables(engine)
    job_id = uuid4()

    SQLAlchemyProcessingJobRepository(engine).complete(
        job_id,
        CompletedArtifact(job_id=job_id, key=f"checkpoints/{job_id}/result.json"),
    )


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


def test_processing_loop_recovers_unacked_evaluation_without_duplicate_findings(
    caplog: LogCaptureFixture,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_evaluation_metadata.create_all(engine)
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    playbook_id = uuid4()
    version_id = uuid4()
    rule_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            worker_evaluation_metadata.tables["agreements"]
            .insert()
            .values(
                id=agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_type="client_agreement",
            )
        )
        connection.execute(
            worker_evaluation_metadata.tables["legal_playbooks"]
            .insert()
            .values(
                id=playbook_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_family="client_agreement",
            )
        )
        connection.execute(
            worker_evaluation_metadata.tables["playbook_versions"]
            .insert()
            .values(
                id=version_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                playbook_id=playbook_id,
                status="published",
            )
        )
        connection.execute(
            worker_evaluation_metadata.tables["playbook_rules"]
            .insert()
            .values(
                id=rule_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                playbook_version_id=version_id,
                clause_type="limitation_of_liability",
                policy_type="required",
                preferred_language="liability is capped",
                severity="critical",
                evaluation_config={"method": "deterministic"},
            )
        )

    manifest = {
        "schema_version": "document-analysis.v1",
        "clauses": [
            {
                "category": "limitation_of_liability",
                "source_text": "The supplier's liability is capped at the fees paid.",
                "confidence": 0.91,
                "citation_anchor_ids": ["citation-liability"],
                "extraction_version": "clause-rules.v1",
            }
        ],
    }

    class Storage:
        def read(self, key: str) -> bytes:
            assert key == f"checkpoints/{job.id}/placeholder.json"
            return json.dumps(manifest).encode()

    class RedeliveringReceiver:
        def __init__(self) -> None:
            self._messages = [
                ProcessingMessage(job_id=job.id, receipt_handle="receipt-1"),
                ProcessingMessage(job_id=job.id, receipt_handle="receipt-2"),
            ]
            self.received: list[str] = []
            self.acked: list[str] = []

        async def receive(self) -> ProcessingMessage | None:
            message = self._messages.pop(0)
            self.received.append(message.receipt_handle)
            return message

        async def ack(self, message: ProcessingMessage) -> None:
            self.acked.append(message.receipt_handle)
            stop_event.set()

    job = ProcessingJob(
        id=uuid4(),
        agreement_id=agreement_id,
        state="queued",
        attempt_count=0,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    repository = InMemoryRepository(job=job, artifacts=[])
    sink = SQLAlchemyPlaybookEvaluationSink(engine, Storage())
    handler_attempts = 0

    class FailsAfterFirstPersist:
        def completed(self, completed_job: ProcessingJob, artifact: CompletedArtifact) -> None:
            nonlocal handler_attempts
            sink.completed(completed_job, artifact)
            handler_attempts += 1
            if handler_attempts == 1:
                raise RuntimeError("evaluation database temporarily unavailable")

    stop_event = asyncio.Event()
    receiver = RedeliveringReceiver()
    worker = JobProcessor(
        repository,
        InMemoryQueue(retries=[]),
        PlaceholderProcessor(),
        completion_handler=FailsAfterFirstPersist(),
    )

    with caplog.at_level(logging.ERROR, logger="agreement_intelligence.worker"):
        asyncio.run(
            run_processing_loop(
                stop_event,
                receiver=receiver,
                processor=worker,
                idle_sleep_seconds=0,
            )
        )

    with engine.connect() as connection:
        evaluations = connection.execute(
            select(worker_evaluation_metadata.tables["playbook_evaluations"])
        ).all()
        findings = connection.execute(
            select(worker_evaluation_metadata.tables["playbook_findings"])
        ).all()

    assert repository.job.state == "completed"
    assert receiver.received == ["receipt-1", "receipt-2"]
    assert receiver.acked == ["receipt-2"]
    assert handler_attempts == 2
    assert len(evaluations) == 1
    assert len(findings) == 1
    assert [getattr(record, "event", None) for record in caplog.records] == [
        "worker.processing_message.failed"
    ]


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
