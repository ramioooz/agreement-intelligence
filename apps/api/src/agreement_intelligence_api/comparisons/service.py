from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.service import AgreementNotFoundError
from agreement_intelligence_api.comparisons.models import VersionComparisonRunRecord
from agreement_intelligence_api.comparisons.repository import SQLAlchemyVersionComparisonRepository
from agreement_intelligence_api.comparisons.schemas import (
    CreateVersionComparisonRequest,
    VersionComparisonResultResponse,
    VersionComparisonRunResponse,
)
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.models import ProcessingJobRecord
from agreement_intelligence_api.processing.queue import (
    ProcessingOutboxDispatcher,
    ProcessingQueuePublisher,
)
from agreement_intelligence_api.processing.repository import SQLAlchemyProcessingJobRepository


class VersionComparisonConflictError(Exception):
    pass


class VersionComparisonService:
    def __init__(
        self,
        repository: SQLAlchemyVersionComparisonRepository,
        agreements: SQLAlchemyAgreementRepository,
        processing: SQLAlchemyProcessingJobRepository,
        identity: IdentityService,
        queue: ProcessingQueuePublisher,
    ) -> None:
        self._repository = repository
        self._agreements = agreements
        self._processing = processing
        self._identity = identity
        self._queue = queue

    def create(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        idempotency_key: str,
        request: CreateVersionComparisonRequest,
    ) -> tuple[VersionComparisonRunResponse, bool]:
        self._authorize(principal, organization_id, workspace_id)
        agreement = self._agreements.get(agreement_id)
        if (
            agreement is None
            or agreement.organization_id != organization_id
            or agreement.workspace_id != workspace_id
        ):
            raise AgreementNotFoundError
        baseline_id, target_id = self._resolve_versions(agreement_id, request)
        existing_key = self._repository.by_idempotency_key(agreement_id, idempotency_key)
        if existing_key is not None:
            if (
                existing_key.baseline_version_id != baseline_id
                or existing_key.target_version_id != target_id
                or existing_key.analysis_version != request.analysis_version
            ):
                raise VersionComparisonConflictError
            return self._repository.response(existing_key), False
        existing = self._repository.by_identity(
            agreement_id, baseline_id, target_id, request.analysis_version
        )
        if existing is not None:
            return self._repository.response(existing), False
        target = self._agreements.get_version(target_id)
        assert target is not None
        now = datetime.now(UTC)
        comparison = VersionComparisonRunRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            baseline_version_id=baseline_id,
            target_version_id=target_id,
            processing_job_id=None,
            idempotency_key=idempotency_key,
            analysis_version=request.analysis_version,
            state="queued",
            failure_category=None,
            failure_message=None,
            analysis_provenance={
                "mode": "deterministic",
                "analysis_version": request.analysis_version,
            },
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        job = ProcessingJobRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            version_id=target_id,
            idempotency_key=f"comparison:{comparison.id}",
            profile="version-comparison",
            source_storage_key=target.storage_key,
            source_checksum=target.checksum,
            source_content_type=target.content_type,
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
        comparison.processing_job_id = job.id
        try:
            self._repository.create(comparison)
            response = self._processing.create(job)
        except IntegrityError as error:
            self._identity.session.rollback()
            existing = self._repository.by_identity(
                agreement_id, baseline_id, target_id, request.analysis_version
            )
            if existing is not None:
                return self._repository.response(existing), False
            raise error
        self._processing.enqueue_outbox(
            response, idempotency_key=job.idempotency_key, profile=job.profile
        )
        self._identity.session.commit()
        ProcessingOutboxDispatcher(
            session=self._identity.session, publisher=self._queue
        ).dispatch_pending()
        return self._repository.response(comparison), True

    def get(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        comparison_id: UUID,
    ) -> VersionComparisonResultResponse:
        self._authorize(principal, organization_id, workspace_id)
        record = self._repository.get(comparison_id)
        if (
            record is None
            or record.agreement_id != agreement_id
            or record.organization_id != organization_id
            or record.workspace_id != workspace_id
        ):
            raise AgreementNotFoundError
        return self._repository.result(record)

    def _resolve_versions(
        self, agreement_id: UUID, request: CreateVersionComparisonRequest
    ) -> tuple[UUID, UUID]:
        completed = [
            version
            for version in self._agreements.list_versions(agreement_id)
            if version.processing_state == "completed"
        ]
        if request.baseline_version_id is None and request.target_version_id is None:
            if len(completed) < 2:
                raise VersionComparisonConflictError
            baseline, target = completed[-2:]
        elif request.baseline_version_id is None or request.target_version_id is None:
            raise VersionComparisonConflictError
        else:
            resolved_baseline = self._agreements.get_version(request.baseline_version_id)
            resolved_target = self._agreements.get_version(request.target_version_id)
            if resolved_baseline is None or resolved_target is None:
                raise VersionComparisonConflictError
            baseline = resolved_baseline
            target = resolved_target
        if (
            baseline.agreement_id != agreement_id
            or target.agreement_id != agreement_id
            or baseline.processing_state != "completed"
            or target.processing_state != "completed"
            or target.version_number <= baseline.version_number
        ):
            raise VersionComparisonConflictError
        return baseline.id, target.id

    def _authorize(self, principal: Principal, organization_id: UUID, workspace_id: UUID) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_READ,
        ):
            raise AgreementNotFoundError
