import asyncio
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from agreement_intelligence_platform.observability import (
    extract_trace_context,
    inject_trace_context,
    record_metric,
    safe_span_attributes,
)
from agreement_intelligence_platform.telemetry import operation_span
from opentelemetry.context import attach, detach
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

from agreement_intelligence_worker.agreement_deletion import (
    deletion_objects,
    deletion_outbox,
    deletion_requests,
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
    Column("workspace_id", Uuid(as_uuid=True), nullable=True),
    Column("current_version_id", Uuid(as_uuid=True), nullable=True),
    Column("processing_state", String(32), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("deletion_requested_at", DateTime(timezone=True), nullable=True),
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
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("artifact_key", String(500), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_job_key"),
)
processing_artifact_intents = Table(
    "processing_artifact_intents",
    processing_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("job_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False, index=True),
    Column("profile", String(100), nullable=False),
    Column("category", String(32), nullable=False),
    Column("artifact_key", String(1024), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("job_id", name="uq_processing_artifact_intents_job"),
    UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_intent_job_key"),
)


class TransientProcessingError(Exception):
    """A dependency failed in a way that can be retried safely."""


class PermanentProcessingError(Exception):
    """The job cannot succeed without an authorized new submission."""

    def __init__(self, message: str, *, category: str = "permanent") -> None:
        super().__init__(message)
        self.category = category


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
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    trace_headers: Mapping[str, str] = field(default_factory=dict)
    queue_age_ms: int | None = None
    message_type: str = "processing"
    deletion_id: UUID | None = None


class JobRepository(Protocol):
    def claim(
        self,
        job_id: UUID,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ProcessingJob | None: ...

    def expect(self, job: ProcessingJob, artifact: CompletedArtifact) -> bool: ...

    def complete(
        self,
        job_id: UUID,
        artifact: CompletedArtifact,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        claimed_job: ProcessingJob | None = None,
    ) -> bool | None: ...

    def requeue(
        self,
        job_id: UUID,
        *,
        category: str,
        message: str,
        next_retry_at: datetime,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> None: ...

    def fail(
        self,
        job_id: UUID,
        *,
        category: str,
        message: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> None: ...


class ProcessingQueue(Protocol):
    def enqueue(
        self,
        job_id: UUID,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        delay_seconds: int,
    ) -> None: ...


class ProcessingMessageReceiver(Protocol):
    async def receive(self) -> ProcessingMessage | None: ...

    async def ack(self, message: ProcessingMessage) -> None: ...


class DeletionMessageProcessor(Protocol):
    def handle(self, deletion_id: UUID, *, organization_id: UUID, workspace_id: UUID) -> None: ...


class AgreementProcessor(Protocol):
    def expected_artifact(self, job: ProcessingJob) -> CompletedArtifact: ...

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

    def handle(
        self,
        job_id: UUID,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> None:
        if organization_id is None or workspace_id is None:
            job = self._repository.claim(job_id)
        else:
            job = self._repository.claim(
                job_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        if job is None:
            self._recover_completed_evaluation(
                job_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
            return
        try:
            expected_artifact = self._processor.expected_artifact(job)
            if not self._repository.expect(job, expected_artifact):
                return
            artifact = self._processor.process(job)
        except TransientProcessingError as error:
            self._handle_transient_failure(job, str(error))
        except PermanentProcessingError as error:
            self._fail(job, category=error.category, message=_safe_summary(str(error)))
        except Exception:
            self._handle_transient_failure(job, "Unexpected processing dependency failure")
        else:
            if artifact != expected_artifact:
                raise RuntimeError("processor returned an artifact outside its durable intent")
            if not self._complete(job, artifact):
                discard = getattr(self._processor, "discard", None)
                if callable(discard):
                    discard(artifact)
                return
            if self._completion_handler is not None:
                self._completion_handler.completed(job, artifact)

    def _recover_completed_evaluation(
        self,
        job_id: UUID,
        *,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> None:
        if self._completion_handler is None:
            return
        completed_artifact = getattr(self._repository, "completed_artifact", None)
        if not callable(completed_artifact):
            return
        if organization_id is None or workspace_id is None:
            recovered = completed_artifact(job_id)
        else:
            recovered = completed_artifact(
                job_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        if recovered is None:
            return
        job, artifact = recovered
        self._completion_handler.completed(job, artifact)

    def _handle_transient_failure(self, job: ProcessingJob, message: str) -> None:
        safe_message = _safe_summary(message)
        if not self._retry_policy.may_retry(job.attempt_count):
            self._fail(job, category="transient_exhausted", message=safe_message)
            return
        delay_seconds = self._retry_policy.delay_seconds(job.attempt_count)
        record_metric(
            "agreement_intelligence.retry.count",
            1,
            operation="worker.processing",
            outcome="retry",
        )
        self._requeue(
            job,
            message=safe_message,
            next_retry_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
        )
        self._queue.enqueue(
            job.id,
            organization_id=_required_tenant_scope(job.organization_id, "organization_id"),
            workspace_id=_required_tenant_scope(job.workspace_id, "workspace_id"),
            delay_seconds=delay_seconds,
        )

    def _complete(self, job: ProcessingJob, artifact: CompletedArtifact) -> bool:
        completed = self._repository.complete(
            job.id,
            artifact,
            organization_id=_required_tenant_scope(job.organization_id, "organization_id"),
            workspace_id=_required_tenant_scope(job.workspace_id, "workspace_id"),
            claimed_job=job,
        )
        return completed is not False

    def _requeue(self, job: ProcessingJob, *, message: str, next_retry_at: datetime) -> None:
        self._repository.requeue(
            job.id,
            category="transient",
            message=message,
            next_retry_at=next_retry_at,
            organization_id=_required_tenant_scope(job.organization_id, "organization_id"),
            workspace_id=_required_tenant_scope(job.workspace_id, "workspace_id"),
        )

    def _fail(self, job: ProcessingJob, *, category: str, message: str) -> None:
        self._repository.fail(
            job.id,
            category=category,
            message=message,
            organization_id=_required_tenant_scope(job.organization_id, "organization_id"),
            workspace_id=_required_tenant_scope(job.workspace_id, "workspace_id"),
        )


class PlaceholderAgreementProcessor:
    def expected_artifact(self, job: ProcessingJob) -> CompletedArtifact:
        return CompletedArtifact(job_id=job.id, key=f"checkpoints/{job.id}/placeholder.json")

    def process(self, job: ProcessingJob) -> CompletedArtifact:
        return self.expected_artifact(job)


class SQSProcessingQueue:
    def __init__(self, *, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue(
        self,
        job_id: UUID,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        delay_seconds: int,
    ) -> None:
        request: dict[str, object] = {
            "QueueUrl": self._queue_url,
            "MessageBody": json.dumps(
                {
                    "job_id": str(job_id),
                    "organization_id": str(organization_id),
                    "workspace_id": str(workspace_id),
                },
                sort_keys=True,
            ),
            "DelaySeconds": delay_seconds,
        }
        trace_headers: dict[str, str] = {}
        inject_trace_context(trace_headers)
        if trace_headers:
            request["MessageAttributes"] = {
                key: {"DataType": "String", "StringValue": value}
                for key, value in trace_headers.items()
            }
        if _is_fifo_queue(self._queue_url):
            deduplication_suffix = datetime.now(UTC).isoformat()
            request["MessageGroupId"] = str(job_id)
            request["MessageDeduplicationId"] = (
                f"{job_id}:retry:{delay_seconds}:{deduplication_suffix}"
            )
        self._client.send_message(**request)

    def enqueue_deletion(
        self,
        deletion_id: UUID,
        *,
        agreement_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        delay_seconds: int,
    ) -> None:
        body = json.dumps(
            {
                "message_type": "agreement_deletion",
                "deletion_id": str(deletion_id),
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "agreement_id": str(agreement_id),
            },
            sort_keys=True,
        )
        request: dict[str, object] = {
            "QueueUrl": self._queue_url,
            "MessageBody": body,
            "DelaySeconds": delay_seconds,
        }
        if _is_fifo_queue(self._queue_url):
            request.pop("DelaySeconds")
            request["MessageGroupId"] = str(agreement_id)
            request["MessageDeduplicationId"] = (
                f"{deletion_id}:retry:{delay_seconds}:{datetime.now(UTC).isoformat()}"
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
            MessageAttributeNames=["traceparent", "tracestate"],
            AttributeNames=["SentTimestamp"],
        )
        messages = result.get("Messages", [])
        if not messages:
            return None
        message = messages[0]
        body = json.loads(str(message["Body"]))
        message_attributes = cast(
            Mapping[str, Mapping[str, object]], message.get("MessageAttributes", {})
        )
        trace_headers = {
            key: value
            for key, attribute in message_attributes.items()
            if key in {"traceparent", "tracestate"}
            and isinstance(value := attribute.get("StringValue"), str)
        }
        message_type = str(body.get("message_type", "processing"))
        deletion_id = (
            UUID(str(body["deletion_id"])) if message_type == "agreement_deletion" else None
        )
        return ProcessingMessage(
            job_id=UUID(str(body.get("job_id", deletion_id))),
            organization_id=UUID(str(body["organization_id"])),
            workspace_id=UUID(str(body["workspace_id"])),
            receipt_handle=str(message["ReceiptHandle"]),
            trace_headers=trace_headers,
            queue_age_ms=_queue_age_ms(message),
            message_type=message_type,
            deletion_id=deletion_id,
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

    def claim(
        self,
        job_id: UUID,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> ProcessingJob | None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                if organization_id is None or workspace_id is None:
                    raise ValueError("processing message is missing tenant scope")
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(organization_id)},
                )
            job = (
                connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
                .mappings()
                .one_or_none()
            )
            if job is None:
                intent = _artifact_intent(
                    connection,
                    job_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    lock=False,
                )
                if intent is not None:
                    agreement = _agreement_for_update(connection, intent)
                    if agreement is None or agreement["deletion_requested_at"] is None:
                        raise RuntimeError("orphaned processing artifact intent")
                    locked_intent = _artifact_intent(
                        connection,
                        job_id,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        lock=True,
                    )
                    if locked_intent is not None:
                        _reconcile_artifact_intent(connection, locked_intent, now=now)
                return None
            if organization_id is not None and job["organization_id"] != organization_id:
                return None
            if workspace_id is not None and job["workspace_id"] != workspace_id:
                return None
            agreement = _agreement_for_update(connection, cast(Mapping[str, Any], job))
            if agreement is None:
                return None
            if agreement["deletion_requested_at"] is not None:
                intent = _artifact_intent(
                    connection,
                    job_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    lock=True,
                )
                if intent is not None:
                    _reconcile_artifact_intent(connection, intent, now=now)
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

    def expect(self, job: ProcessingJob, artifact: CompletedArtifact) -> bool:
        now = datetime.now(UTC)
        organization_id = _required_tenant_scope(job.organization_id, "organization_id")
        workspace_id = _required_tenant_scope(job.workspace_id, "workspace_id")
        category = _late_artifact_category(job.profile or "", artifact.key)
        if category is None:
            return True
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id, workspace_id)
            agreement = _agreement_for_update(
                connection,
                {
                    "agreement_id": job.agreement_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            )
            if agreement is None:
                return False
            intent = _artifact_intent(
                connection,
                job.id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                lock=True,
            )
            values = {
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": job.agreement_id,
                "profile": job.profile or "",
                "category": category,
                "artifact_key": artifact.key,
                "updated_at": now,
            }
            if intent is None:
                connection.execute(
                    processing_artifact_intents.insert().values(
                        id=uuid4(), job_id=job.id, created_at=now, **values
                    )
                )
                intent = {"id": None, "job_id": job.id, **values}
            elif intent["artifact_key"] != artifact.key or intent["category"] != category:
                raise RuntimeError("processing artifact intent changed after reservation")
            if agreement["deletion_requested_at"] is not None:
                _reconcile_artifact_intent(connection, intent, now=now)
                return False
            return True

    def complete(
        self,
        job_id: UUID,
        artifact: CompletedArtifact,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        claimed_job: ProcessingJob | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id, workspace_id)
            job = (
                connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
                .mappings()
                .one_or_none()
            )
            if job is None and claimed_job is None:
                return False
            if job is None:
                assert claimed_job is not None
                job_context: Mapping[str, Any] = {
                    "id": claimed_job.id,
                    "agreement_id": claimed_job.agreement_id,
                    "organization_id": claimed_job.organization_id,
                    "workspace_id": claimed_job.workspace_id,
                    "profile": claimed_job.profile,
                }
            else:
                job_context = cast(Mapping[str, Any], job)
            if not _matches_tenant_scope(job_context, organization_id, workspace_id):
                return False
            agreement = _agreement_for_update(connection, job_context)
            job = _job_for_update(connection, job_id)
            if agreement is None:
                return False
            if agreement["deletion_requested_at"] is not None:
                _inventory_late_artifact(connection, job or job_context, artifact.key, now=now)
                connection.execute(
                    processing_artifact_intents.delete().where(
                        processing_artifact_intents.c.job_id == job_id
                    )
                )
                return False
            if job is None:
                return False
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
                        organization_id=job["organization_id"],
                        workspace_id=job["workspace_id"],
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
            connection.execute(
                processing_artifact_intents.delete().where(
                    processing_artifact_intents.c.job_id == job_id
                )
            )
            return True

    def completed_artifact(
        self,
        job_id: UUID,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> tuple[ProcessingJob, CompletedArtifact] | None:
        with self._engine.connect() as connection:
            _set_tenant_context(connection, organization_id, workspace_id)
            job = (
                connection.execute(select(processing_jobs).where(processing_jobs.c.id == job_id))
                .mappings()
                .one_or_none()
            )
            if job is None or job["state"] != "completed":
                return None
            if not _matches_tenant_scope(job, organization_id, workspace_id):
                return None
            deletion_requested_at = connection.scalar(
                select(agreements.c.deletion_requested_at).where(
                    agreements.c.id == job["agreement_id"],
                    agreements.c.organization_id == job["organization_id"],
                )
            )
            if deletion_requested_at is not None:
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
        self,
        job_id: UUID,
        *,
        category: str,
        message: str,
        next_retry_at: datetime,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id, workspace_id)
            job = _job_for_update(connection, job_id)
            if job is None:
                return
            if not _matches_tenant_scope(job, organization_id, workspace_id):
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

    def fail(
        self,
        job_id: UUID,
        *,
        category: str,
        message: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            _set_tenant_context(connection, organization_id, workspace_id)
            job = _job_for_update(connection, job_id)
            if job is None:
                return
            if not _matches_tenant_scope(job, organization_id, workspace_id):
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
        connection.execute(
            select(processing_jobs).where(processing_jobs.c.id == job_id).with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _artifact_intent(
    connection: Any,
    job_id: UUID,
    *,
    organization_id: UUID | None,
    workspace_id: UUID | None,
    lock: bool,
) -> Any | None:
    statement = select(processing_artifact_intents).where(
        processing_artifact_intents.c.job_id == job_id
    )
    if organization_id is not None:
        statement = statement.where(
            processing_artifact_intents.c.organization_id == organization_id
        )
    if workspace_id is not None:
        statement = statement.where(processing_artifact_intents.c.workspace_id == workspace_id)
    if lock:
        statement = statement.with_for_update()
    return connection.execute(statement).mappings().one_or_none()


def _agreement_for_update(connection: Any, context: Mapping[str, Any]) -> Any | None:
    return (
        connection.execute(
            select(agreements)
            .where(
                agreements.c.id == context["agreement_id"],
                agreements.c.organization_id == context["organization_id"],
                agreements.c.workspace_id == context["workspace_id"],
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _reconcile_artifact_intent(
    connection: Any, intent: Mapping[str, Any], *, now: datetime
) -> None:
    _inventory_late_artifact(connection, intent, cast(str, intent["artifact_key"]), now=now)
    connection.execute(
        processing_artifact_intents.delete().where(
            processing_artifact_intents.c.job_id == intent["job_id"]
        )
    )


def _inventory_late_artifact(
    connection: Any, job: Mapping[str, Any], key: str, *, now: datetime
) -> None:
    request = (
        connection.execute(
            select(deletion_requests)
            .where(
                deletion_requests.c.agreement_id == job["agreement_id"],
                deletion_requests.c.organization_id == job["organization_id"],
                deletion_requests.c.workspace_id == job["workspace_id"],
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if request is None:
        raise RuntimeError("tombstoned agreement has no active deletion request")

    category = _late_artifact_category(cast(str, job["profile"]), key)
    if category is None:
        return
    existing = connection.execute(
        select(deletion_objects.c.id, deletion_objects.c.state).where(
            deletion_objects.c.deletion_id == request["id"],
            deletion_objects.c.category == category,
            deletion_objects.c.object_key == key,
        )
    ).one_or_none()
    if existing is None:
        connection.execute(
            deletion_objects.insert().values(
                id=uuid4(),
                deletion_id=request["id"],
                organization_id=job["organization_id"],
                workspace_id=job["workspace_id"],
                agreement_id=job["agreement_id"],
                category=category,
                object_key=key,
                state="pending",
                last_error=None,
                updated_at=now,
            )
        )
    elif existing.state != "pending":
        connection.execute(
            update(deletion_objects)
            .where(deletion_objects.c.id == existing.id)
            .values(state="pending", last_error=None, updated_at=now)
        )

    terminal_state = request["state"] in {"completed", "failed"}
    retry_cycle = int(request["retry_cycle"]) + (1 if terminal_state else 0)
    connection.execute(
        update(deletion_requests)
        .where(deletion_requests.c.id == request["id"])
        .values(
            state="retrying",
            attempt_count=0 if terminal_state else request["attempt_count"],
            retry_cycle=retry_cycle,
            claim_token=None,
            lease_expires_at=None,
            next_attempt_at=now,
            failure_category="artifact_race",
            failure_message="Processing completed after deletion was accepted",
            completed_at=None,
            failed_at=None,
            updated_at=now,
        )
    )
    result = connection.execute(
        update(deletion_outbox)
        .where(deletion_outbox.c.deletion_id == request["id"])
        .values(
            attempt_count=0,
            next_attempt_at=now,
            lease_token=None,
            lease_expires_at=None,
            last_error=None,
            delivered_at=None,
            updated_at=now,
        )
    )
    if result.rowcount == 0:
        connection.execute(
            deletion_outbox.insert().values(
                id=uuid4(),
                deletion_id=request["id"],
                organization_id=job["organization_id"],
                workspace_id=job["workspace_id"],
                agreement_id=job["agreement_id"],
                attempt_count=0,
                next_attempt_at=now,
                lease_token=None,
                lease_expires_at=None,
                last_error=None,
                delivered_at=None,
                updated_at=now,
            )
        )


def _late_artifact_category(profile: str, key: str) -> str | None:
    if profile.startswith("embedding-reindex:") or key.startswith("embedding-reindex/"):
        return None
    if profile == "version-comparison":
        return "comparison"
    return "analysis"


def _required_tenant_scope(value: UUID | None, field_name: str) -> UUID:
    if value is None:
        raise ValueError(f"processing job is missing {field_name}")
    return value


def _set_tenant_context(
    connection: Any, organization_id: UUID | None, workspace_id: UUID | None
) -> None:
    if connection.dialect.name != "postgresql":
        return
    if organization_id is None or workspace_id is None:
        raise ValueError("processing message is missing tenant scope")
    connection.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(organization_id)},
    )


def _matches_tenant_scope(
    job: Any, organization_id: UUID | None, workspace_id: UUID | None
) -> bool:
    return (organization_id is None or job["organization_id"] == organization_id) and (
        workspace_id is None or job["workspace_id"] == workspace_id
    )


def _update_agreement_processing_state(
    connection: Any,
    job: Any,
    *,
    state: JobState,
    updated_at: datetime,
) -> None:
    if str(job["profile"]).startswith("embedding-reindex:"):
        return
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
    deletion_processor: DeletionMessageProcessor | None = None,
    idle_sleep_seconds: float = 1.0,
) -> None:
    while not stop_event.is_set():
        receive_state = {"outcome": "success"}
        with operation_span(
            "agreement-intelligence.worker",
            "queue.receive",
            safe_span_attributes(
                {"operation": "queue.receive", "outcome": receive_state["outcome"]}
            ),
            outcome_getter=partial(_receive_outcome, receive_state),
        ) as receive_span:
            message = await receiver.receive()
            if message is None:
                receive_state["outcome"] = "skipped"
            elif message.queue_age_ms is not None:
                receive_span.set_attributes(
                    cast(Any, safe_span_attributes({"queue_age_ms": message.queue_age_ms}))
                )
                record_metric(
                    "agreement_intelligence.queue.age_ms",
                    message.queue_age_ms,
                    operation="queue.receive",
                    outcome="success",
                )
        if message is None:
            await asyncio.sleep(idle_sleep_seconds)
            continue
        try:
            context_token = attach(extract_trace_context(message.trace_headers))
            try:
                with operation_span(
                    "agreement-intelligence.worker",
                    "worker.processing",
                    safe_span_attributes({"operation": "worker.processing", "outcome": "success"}),
                ):
                    if message.message_type == "agreement_deletion":
                        if deletion_processor is None or message.deletion_id is None:
                            raise ValueError("agreement deletion processor is not configured")
                        organization_id = _required_tenant_scope(
                            message.organization_id, "organization_id"
                        )
                        workspace_id = _required_tenant_scope(message.workspace_id, "workspace_id")
                        deletion_processor.handle(
                            message.deletion_id,
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                        )
                    else:
                        processor.handle(
                            message.job_id,
                            organization_id=message.organization_id,
                            workspace_id=message.workspace_id,
                        )
            finally:
                detach(context_token)
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


def _receive_outcome(state: Mapping[str, str]) -> str:
    return state["outcome"]


def _queue_age_ms(message: Mapping[str, object]) -> int | None:
    attributes = message.get("Attributes")
    if not isinstance(attributes, Mapping):
        return None
    sent_at = attributes.get("SentTimestamp")
    if not isinstance(sent_at, str) or not sent_at.isdecimal():
        return None
    return max(0, round(datetime.now(UTC).timestamp() * 1_000) - int(sent_at))
