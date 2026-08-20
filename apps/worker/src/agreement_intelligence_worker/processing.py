import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    create_engine,
    func,
    select,
    text,
    update,
)

logger = logging.getLogger("agreement_intelligence.worker")

JobState = Literal["queued", "processing", "completed", "failed"]
_SENSITIVE_MESSAGE_PATTERN = re.compile(
    r"\b(agreement|bearer|credential|password|secret|token)\b",
    re.IGNORECASE,
)
processing_metadata = MetaData()
agreements = Table(
    "agreements",
    processing_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("current_version_id", Uuid(as_uuid=True), nullable=True),
    Column("processing_state", String(32), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
agreement_versions = Table(
    "agreement_versions",
    processing_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("processing_state", String(32), nullable=False),
)
processing_jobs = Table(
    "processing_jobs",
    processing_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("version_id", Uuid(as_uuid=True), nullable=True),
    Column("idempotency_key", String(255), nullable=False),
    Column("profile", String(100), nullable=False),
    Column("source_storage_key", String(1024), nullable=True),
    Column("source_checksum", String(255), nullable=True),
    Column("source_content_type", String(100), nullable=True),
    Column("state", String(32), nullable=False, index=True),
    Column("attempt_count", Integer, nullable=False),
    Column("failure_category", String(64), nullable=True),
    Column("failure_message", String(500), nullable=True),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("queued_at", DateTime(timezone=True), nullable=False),
    Column("processing_started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("failed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("agreement_id", "idempotency_key", name="uq_processing_job_idempotency"),
    Index("ix_processing_jobs_agreement_state", "agreement_id", "state"),
)
processing_artifacts = Table(
    "processing_artifacts",
    processing_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("job_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("artifact_key", String(500), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_job_key"),
)


class TransientProcessingError(Exception):
    """A dependency failed in a way that can be retried safely."""


class PermanentProcessingError(Exception):
    """The job cannot succeed without an authorized new submission."""


@dataclass(frozen=True)
class ProcessingJob:
    id: UUID
    agreement_id: UUID
    state: JobState
    attempt_count: int
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    profile: str | None = None
    source_storage_key: str | None = None
    source_checksum: str | None = None
    source_content_type: str | None = None
    failure_category: str | None = None
    failure_message: str | None = None
    next_retry_at: datetime | None = None
    processing_started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class CompletedArtifact:
    job_id: UUID
    key: str


@dataclass(frozen=True)
class ProcessingMessage:
    job_id: UUID
    receipt_handle: str


class JobRepository(Protocol):
    def claim(self, job_id: UUID) -> ProcessingJob | None: ...

    def complete(self, job_id: UUID, artifact: CompletedArtifact) -> None: ...

    def requeue(
        self, job_id: UUID, *, category: str, message: str, next_retry_at: datetime
    ) -> None: ...

    def fail(self, job_id: UUID, *, category: str, message: str) -> None: ...


class ProcessingQueue(Protocol):
    def enqueue(self, job_id: UUID, *, delay_seconds: int) -> None: ...


class ProcessingMessageReceiver(Protocol):
    async def receive(self) -> ProcessingMessage | None: ...

    async def ack(self, message: ProcessingMessage) -> None: ...


class AgreementProcessor(Protocol):
    def process(self, job: ProcessingJob) -> CompletedArtifact: ...


class CompletionHandler(Protocol):
    def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None: ...


@dataclass(frozen=True)
class CompletionHandlerFanout:
    handlers: tuple[CompletionHandler, ...]

    def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
        for handler in self.handlers:
            handler.completed(job, artifact)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 2
    max_delay_seconds: int = 60

    def delay_seconds(self, attempt_count: int) -> int:
        if attempt_count < 1:
            raise ValueError("attempt_count must be positive")
        return int(
            min(
                self.base_delay_seconds * (2 ** (attempt_count - 1)),
                self.max_delay_seconds,
            )
        )

    def may_retry(self, attempt_count: int) -> bool:
        return attempt_count < self.max_attempts


class JobProcessor:
    """Claims durable jobs and turns at-least-once delivery into idempotent processing."""

    def __init__(
        self,
        repository: JobRepository,
        queue: ProcessingQueue,
        processor: AgreementProcessor,
        *,
        retry_policy: RetryPolicy | None = None,
        completion_handler: CompletionHandler | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._processor = processor
        self._retry_policy = retry_policy or RetryPolicy()
        self._completion_handler = completion_handler

    def handle(self, job_id: UUID) -> None:
        job = self._repository.claim(job_id)
        if job is None:
            self._recover_completed_evaluation(job_id)
            return
        try:
            artifact = self._processor.process(job)
        except TransientProcessingError as error:
            self._handle_transient_failure(job, str(error))
        except PermanentProcessingError as error:
            self._repository.fail(job.id, category="permanent", message=_safe_summary(str(error)))
        except Exception:
            self._handle_transient_failure(job, "Unexpected processing dependency failure")
        else:
            self._repository.complete(job.id, artifact)
            if self._completion_handler is not None:
                self._completion_handler.completed(job, artifact)

    def _recover_completed_evaluation(self, job_id: UUID) -> None:
        if self._completion_handler is None:
            return
        completed_artifact = getattr(self._repository, "completed_artifact", None)
        if not callable(completed_artifact):
            return
        recovered = completed_artifact(job_id)
        if recovered is None:
            return
        job, artifact = recovered
        self._completion_handler.completed(job, artifact)

    def _handle_transient_failure(self, job: ProcessingJob, message: str) -> None:
        safe_message = _safe_summary(message)
        if not self._retry_policy.may_retry(job.attempt_count):
            self._repository.fail(
                job.id,
                category="transient_exhausted",
                message=safe_message,
            )
            return
        delay_seconds = self._retry_policy.delay_seconds(job.attempt_count)
        self._repository.requeue(
            job.id,
            category="transient",
            message=safe_message,
            next_retry_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
        )
        self._queue.enqueue(job.id, delay_seconds=delay_seconds)


class PlaceholderAgreementProcessor:
    def process(self, job: ProcessingJob) -> CompletedArtifact:
        return CompletedArtifact(job_id=job.id, key=f"checkpoints/{job.id}/placeholder.json")


class SQSProcessingQueue:
    def __init__(self, *, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue(self, job_id: UUID, *, delay_seconds: int) -> None:
        request: dict[str, object] = {
            "QueueUrl": self._queue_url,
            "MessageBody": json.dumps({"job_id": str(job_id)}, sort_keys=True),
            "DelaySeconds": delay_seconds,
        }
        if _is_fifo_queue(self._queue_url):
            deduplication_suffix = datetime.now(UTC).isoformat()
            request["MessageGroupId"] = str(job_id)
            request["MessageDeduplicationId"] = (
                f"{job_id}:retry:{delay_seconds}:{deduplication_suffix}"
            )
        self._client.send_message(**request)


class SQSProcessingMessageReceiver:
    def __init__(
        self,
        *,
        client: Any,
        queue_url: str,
        wait_time_seconds: int = 10,
    ) -> None:
        self._client = client
        self._queue_url = queue_url
        self._wait_time_seconds = wait_time_seconds

    async def receive(self) -> ProcessingMessage | None:
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
        return ProcessingMessage(
            job_id=UUID(str(body["job_id"])),
            receipt_handle=str(message["ReceiptHandle"]),
        )

    async def ack(self, message: ProcessingMessage) -> None:
        await asyncio.to_thread(
            self._client.delete_message,
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
        )


class SQLAlchemyProcessingJobRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(self, job_id: UUID) -> ProcessingJob | None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            job = (
                connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
                .mappings()
                .one_or_none()
            )
            if job is None:
                return None
            artifact_exists = (
                connection.execute(
                    select(processing_artifacts.c.id)
                    .where(processing_artifacts.c.job_id == job_id)
                    .limit(1)
                ).one_or_none()
                is not None
            )
            if artifact_exists:
                if job["state"] != "completed":
                    connection.execute(
                        update(processing_jobs)
                        .where(processing_jobs.c.id == job_id)
                        .values(
                            state="completed",
                            completed_at=now,
                            failure_category=None,
                            failure_message=None,
                            next_retry_at=None,
                            updated_at=now,
                        )
                    )
                _update_agreement_processing_state(
                    connection, job, state="completed", updated_at=now
                )
                return None
            if job["state"] == "processing":
                _update_agreement_processing_state(
                    connection, job, state="processing", updated_at=now
                )
                return ProcessingJob(
                    id=job_id,
                    agreement_id=cast(UUID, job["agreement_id"]),
                    state="processing",
                    attempt_count=int(job["attempt_count"]),
                    organization_id=cast(UUID, job["organization_id"]),
                    workspace_id=cast(UUID, job["workspace_id"]),
                    profile=cast(str, job["profile"]),
                    source_storage_key=cast(str | None, job["source_storage_key"]),
                    source_checksum=cast(str | None, job["source_checksum"]),
                    source_content_type=cast(str | None, job["source_content_type"]),
                    processing_started_at=cast(datetime | None, job["processing_started_at"]),
                )
            if job["state"] != "queued":
                return None
            attempt_count = int(job["attempt_count"]) + 1
            connection.execute(
                update(processing_jobs)
                .where(processing_jobs.c.id == job_id)
                .values(
                    state="processing",
                    attempt_count=attempt_count,
                    processing_started_at=now,
                    failure_category=None,
                    failure_message=None,
                    next_retry_at=None,
                    updated_at=now,
                )
            )
            _update_agreement_processing_state(connection, job, state="processing", updated_at=now)
            return ProcessingJob(
                id=job_id,
                agreement_id=cast(UUID, job["agreement_id"]),
                state="processing",
                attempt_count=attempt_count,
                organization_id=cast(UUID, job["organization_id"]),
                workspace_id=cast(UUID, job["workspace_id"]),
                profile=cast(str, job["profile"]),
                source_storage_key=cast(str | None, job["source_storage_key"]),
                source_checksum=cast(str | None, job["source_checksum"]),
                source_content_type=cast(str | None, job["source_content_type"]),
                processing_started_at=now,
            )

    def complete(self, job_id: UUID, artifact: CompletedArtifact) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            job = (
                connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
                .mappings()
                .one_or_none()
            )
            if job is None:
                return
            existing_artifact = connection.execute(
                select(processing_artifacts.c.id).where(
                    processing_artifacts.c.job_id == job_id,
                    processing_artifacts.c.artifact_key == artifact.key,
                )
            ).one_or_none()
            if existing_artifact is None:
                connection.execute(
                    processing_artifacts.insert().values(
                        id=uuid4(),
                        job_id=job_id,
                        agreement_id=job["agreement_id"],
                        artifact_key=artifact.key,
                        created_at=now,
                    )
                )
            connection.execute(
                update(processing_jobs)
                .where(processing_jobs.c.id == job_id)
                .values(
                    state="completed",
                    completed_at=now,
                    failure_category=None,
                    failure_message=None,
                    next_retry_at=None,
                    updated_at=now,
                )
            )
            _update_agreement_processing_state(connection, job, state="completed", updated_at=now)

    def completed_artifact(self, job_id: UUID) -> tuple[ProcessingJob, CompletedArtifact] | None:
        with self._engine.connect() as connection:
            job = (
                connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
                .mappings()
                .one_or_none()
            )
            if job is None or job["state"] != "completed":
                return None
            artifact = (
                connection.execute(
                    select(processing_artifacts.c.artifact_key)
                    .where(processing_artifacts.c.job_id == job_id)
                    .order_by(processing_artifacts.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if artifact is None:
                return None
            return (
                ProcessingJob(
                    id=job_id,
                    agreement_id=cast(UUID, job["agreement_id"]),
                    state="completed",
                    attempt_count=int(job["attempt_count"]),
                    organization_id=cast(UUID, job["organization_id"]),
                    workspace_id=cast(UUID, job["workspace_id"]),
                    profile=cast(str, job["profile"]),
                    source_storage_key=cast(str | None, job["source_storage_key"]),
                    source_checksum=cast(str | None, job["source_checksum"]),
                    source_content_type=cast(str | None, job["source_content_type"]),
                    completed_at=cast(datetime | None, job["completed_at"]),
                ),
                CompletedArtifact(job_id=job_id, key=cast(str, artifact["artifact_key"])),
            )

    def requeue(
        self, job_id: UUID, *, category: str, message: str, next_retry_at: datetime
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            job = _job_for_update(connection, job_id)
            if job is None:
                return
            connection.execute(
                update(processing_jobs)
                .where(processing_jobs.c.id == job_id)
                .values(
                    state="queued",
                    failure_category=category,
                    failure_message=message,
                    next_retry_at=next_retry_at,
                    updated_at=now,
                )
            )
            _update_agreement_processing_state(connection, job, state="queued", updated_at=now)

    def fail(self, job_id: UUID, *, category: str, message: str) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            job = _job_for_update(connection, job_id)
            if job is None:
                return
            connection.execute(
                update(processing_jobs)
                .where(processing_jobs.c.id == job_id)
                .values(
                    state="failed",
                    failure_category=category,
                    failure_message=message,
                    failed_at=now,
                    updated_at=now,
                )
            )
            _update_agreement_processing_state(connection, job, state="failed", updated_at=now)


def create_processing_tables(engine: Engine) -> None:
    processing_metadata.create_all(engine)


def processing_engine_from_url(database_url: str) -> Engine:
    return create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))


def _is_fifo_queue(queue_url: str) -> bool:
    return queue_url.rsplit("/", 1)[-1].endswith(".fifo")


def _job_for_update(connection: Any, job_id: UUID) -> Any | None:
    return (
        connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
        .mappings()
        .one_or_none()
    )


def _update_agreement_processing_state(
    connection: Any,
    job: Any,
    *,
    state: JobState,
    updated_at: datetime,
) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(job["organization_id"])},
        )
    version_id = cast(UUID | None, job["version_id"])
    agreement_scope = [
        agreements.c.id == job["agreement_id"],
        agreements.c.organization_id == job["organization_id"],
    ]
    if version_id is not None:
        agreement_scope.append(agreements.c.current_version_id == version_id)
        connection.execute(
            update(agreement_versions)
            .where(
                agreement_versions.c.id == version_id,
                agreement_versions.c.agreement_id == job["agreement_id"],
                agreement_versions.c.organization_id == job["organization_id"],
                agreement_versions.c.workspace_id == job["workspace_id"],
            )
            .values(processing_state=state)
        )
    connection.execute(
        update(agreements)
        .where(*agreement_scope)
        .values(processing_state=state, updated_at=updated_at)
    )


async def run_processing_loop(
    stop_event: asyncio.Event,
    *,
    receiver: ProcessingMessageReceiver,
    processor: JobProcessor,
    idle_sleep_seconds: float = 1.0,
) -> None:
    while not stop_event.is_set():
        message = await receiver.receive()
        if message is None:
            await asyncio.sleep(idle_sleep_seconds)
            continue
        try:
            processor.handle(message.job_id)
        except Exception:
            logger.exception(
                "processing message handling failed",
                extra={
                    "correlation_id": str(message.job_id),
                    "event": "worker.processing_message.failed",
                    "service": "worker",
                },
            )
            continue
        await receiver.ack(message)


def _safe_summary(message: str) -> str:
    normalized = " ".join(message.split())
    if _SENSITIVE_MESSAGE_PATTERN.search(normalized):
        return "Processing dependency failure"
    return (normalized or "Processing failed")[:500]
