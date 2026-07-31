from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.service import AgreementNotFoundError
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.models import ProcessingJobRecord
from agreement_intelligence_api.processing.queue import (
    ProcessingOutboxDispatcher,
    ProcessingQueuePublisher,
)
from agreement_intelligence_api.processing.repository import SQLAlchemyProcessingJobRepository
from agreement_intelligence_api.processing.schemas import (
    ProcessingJobResponse,
    SubmitProcessingJobRequest,
)


class IdempotencyKeyConflictError(Exception):
    pass


class RetryNotPermittedError(Exception):
    pass


class ProcessingJobService:
    def __init__(
        self,
        repository: SQLAlchemyProcessingJobRepository,
        agreements: SQLAlchemyAgreementRepository,
        identity: IdentityService,
        queue: ProcessingQueuePublisher,
    ) -> None:
        self._repository = repository
        self._agreements = agreements
        self._identity = identity
        self._queue = queue

    def submit(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        idempotency_key: str,
        request: SubmitProcessingJobRequest,
    ) -> tuple[ProcessingJobResponse, bool]:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        self._agreement_in_scope(
            agreement_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        existing = self._repository.by_idempotency_key(agreement_id, idempotency_key)
        if existing is not None:
            if existing.profile != request.profile:
                raise IdempotencyKeyConflictError
            return self._repository.response(existing), False

        now = datetime.now(UTC)
        job = ProcessingJobRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            idempotency_key=idempotency_key,
            profile=request.profile,
            state="queued",
            attempt_count=0,
            failure_category=None,
            failure_message=None,
            next_retry_at=None,
            queued_at=now,
            processing_started_at=None,
            completed_at=None,
            failed_at=None,
            created_at=now,
            updated_at=now,
        )
        try:
            response = self._repository.create(job)
        except IntegrityError as error:
            self._identity.session.rollback()
            existing = self._repository.by_idempotency_key(agreement_id, idempotency_key)
            if existing is None:
                raise
            if existing.profile != request.profile:
                raise IdempotencyKeyConflictError from error
            return self._repository.response(existing), False
        self._set_agreement_state(agreement_id, state="queued", updated_at=now)
        self._repository.enqueue_outbox(
            response,
            idempotency_key=idempotency_key,
            profile=request.profile,
        )
        self._identity.session.commit()
        self._dispatch_pending()
        return response, True

    def get(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        job_id: UUID,
    ) -> ProcessingJobResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        job = self._job_in_scope(
            agreement_id,
            job_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        return self._repository.response(job)

    def retry(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        job_id: UUID,
    ) -> ProcessingJobResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        job = self._job_in_scope(
            agreement_id,
            job_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if job.state != "failed" or not _can_retry_failure(job.failure_category):
            raise RetryNotPermittedError
        now = datetime.now(UTC)
        job.state = "queued"
        job.failure_category = None
        job.failure_message = None
        job.next_retry_at = None
        job.queued_at = now
        job.updated_at = now
        idempotency_key = job.idempotency_key
        profile = job.profile
        response = self._repository.response(job)
        self._set_agreement_state(agreement_id, state="queued", updated_at=now)
        self._repository.enqueue_outbox(response, idempotency_key=idempotency_key, profile=profile)
        self._identity.session.commit()
        self._dispatch_pending()
        return response

    def _job_in_scope(
        self,
        agreement_id: UUID,
        job_id: UUID,
        *,
        organization_id: UUID,
        workspace_id: UUID,
    ) -> ProcessingJobRecord:
        job = self._repository.get(job_id)
        if (
            job is None
            or job.agreement_id != agreement_id
            or job.organization_id != organization_id
            or job.workspace_id != workspace_id
        ):
            raise AgreementNotFoundError
        return job

    def _agreement_in_scope(
        self,
        agreement_id: UUID,
        *,
        organization_id: UUID,
        workspace_id: UUID,
    ) -> None:
        agreement = self._agreements.get(agreement_id)
        if (
            agreement is None
            or agreement.organization_id != organization_id
            or agreement.workspace_id != workspace_id
        ):
            raise AgreementNotFoundError

    def _set_agreement_state(self, agreement_id: UUID, *, state: str, updated_at: datetime) -> None:
        agreement = self._agreements.get(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError
        self._agreements.replace(
            agreement.model_copy(update={"processing_state": state, "updated_at": updated_at})
        )

    def _authorize(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_UPDATE,
        ):
            raise AgreementNotFoundError

    def _dispatch_pending(self) -> None:
        ProcessingOutboxDispatcher(
            session=self._identity.session,
            publisher=self._queue,
        ).dispatch_pending()


def _can_retry_failure(category: str | None) -> bool:
    return category in {"transient", "transient_exhausted"}
