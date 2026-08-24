from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.processing.models import (
    ProcessingJobRecord,
    ProcessingOutboxRecord,
)
from agreement_intelligence_api.processing.schemas import ProcessingJobResponse


class SQLAlchemyProcessingJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, record: ProcessingJobRecord) -> ProcessingJobResponse:
        self._session.add(record)
        self._session.flush()
        return self._to_response(record)

    def get(self, job_id: UUID) -> ProcessingJobRecord | None:
        return self._session.get(ProcessingJobRecord, job_id)

    def by_idempotency_key(
        self, agreement_id: UUID, idempotency_key: str
    ) -> ProcessingJobRecord | None:
        return self._session.scalar(
            select(ProcessingJobRecord).where(
                ProcessingJobRecord.agreement_id == agreement_id,
                ProcessingJobRecord.idempotency_key == idempotency_key,
            )
        )

    def response(self, record: ProcessingJobRecord) -> ProcessingJobResponse:
        self._session.flush()
        return self._to_response(record)

    def enqueue_outbox(
        self,
        job: ProcessingJobResponse,
        *,
        idempotency_key: str,
        profile: str,
    ) -> ProcessingOutboxRecord:
        record = ProcessingOutboxRecord(
            agreement_id=job.agreement_id,
            job_id=job.id,
            organization_id=job.organization_id,
            workspace_id=job.workspace_id,
            idempotency_key=idempotency_key,
            profile=profile,
            attempt_count=job.attempt_count,
            queued_at=job.queued_at,
            delivered_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self._session.add(record)
        self._session.flush()
        return record

    @staticmethod
    def _to_response(record: ProcessingJobRecord) -> ProcessingJobResponse:
        return ProcessingJobResponse(
            id=record.id,
            organization_id=record.organization_id,
            workspace_id=record.workspace_id,
            agreement_id=record.agreement_id,
            version_id=record.version_id,
            state=record.state,  # type: ignore[arg-type]
            attempt_count=record.attempt_count,
            failure_category=record.failure_category,
            failure_message=record.failure_message,
            next_retry_at=_as_aware_utc(record.next_retry_at),
            queued_at=_as_required_aware_utc(record.queued_at),
            processing_started_at=_as_aware_utc(record.processing_started_at),
            completed_at=_as_aware_utc(record.completed_at),
            failed_at=_as_aware_utc(record.failed_at),
            created_at=_as_required_aware_utc(record.created_at),
            updated_at=_as_required_aware_utc(record.updated_at),
            retry_permitted=record.state == "failed"
            and record.failure_category in {"transient", "transient_exhausted"},
        )


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _as_required_aware_utc(value: datetime) -> datetime:
    converted = _as_aware_utc(value)
    assert converted is not None
    return converted
