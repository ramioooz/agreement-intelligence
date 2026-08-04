from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from agreement_intelligence_api.agreements.models import AgreementVersionRecord
from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.schemas import (
    AgreementFile,
    AgreementVersionListResponse,
    AgreementVersionResponse,
)
from agreement_intelligence_api.agreements.service import AgreementNotFoundError, AgreementService
from agreement_intelligence_api.documents.service import UploadedDocument
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService


class DuplicateAgreementVersionError(Exception):
    pass


class StaleCurrentVersionError(Exception):
    pass


class VersionIdempotencyConflictError(Exception):
    pass


class AgreementVersionService:
    def __init__(
        self,
        repository: SQLAlchemyAgreementRepository,
        identity: IdentityService,
    ) -> None:
        self._repository = repository
        self._identity = identity
        self._agreements = AgreementService(repository, identity)

    def list(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> AgreementVersionListResponse:
        agreement = self._agreements.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        versions = self._repository.list_versions(agreement.id)
        return AgreementVersionListResponse(
            items=[self._repository.version_response(version) for version in versions],
            current_version_id=agreement.current_version_id,
            comparison_baseline_version_id=agreement.comparison_baseline_version_id,
        )

    def get(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        version_id: UUID,
    ) -> AgreementVersionResponse:
        self._agreements.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        version = self._repository.get_version(version_id)
        if version is None or not self._in_scope(
            version,
            agreement_id=agreement_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
        ):
            raise AgreementNotFoundError
        return self._repository.version_response(version)

    def create(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        expected_current_version: int,
        idempotency_key: str,
        uploaded: UploadedDocument,
    ) -> tuple[AgreementVersionResponse, bool]:
        self.authorize_upload(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        agreement = self._agreements.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        existing = self._repository.version_by_idempotency_key(agreement.id, idempotency_key)
        if existing is not None:
            if existing.checksum != uploaded.sha256:
                raise VersionIdempotencyConflictError
            return self._repository.version_response(existing), False

        versions = self._repository.list_versions(agreement.id)
        current = versions[-1] if versions else None
        current_number = current.version_number if current is not None else 0
        if expected_current_version != current_number:
            raise StaleCurrentVersionError
        if self._repository.version_by_checksum(agreement.id, uploaded.sha256) is not None:
            raise DuplicateAgreementVersionError

        now = datetime.now(UTC)
        version_number = current_number + 1
        source = AgreementFile(
            file_name=uploaded.original_filename,
            content_type=uploaded.content_type,
            storage_key=uploaded.object_key,
            checksum=uploaded.sha256,
            byte_size=uploaded.byte_size,
            version_number=version_number,
        )
        record = AgreementVersionRecord(
            id=uuid4(),
            agreement_id=agreement.id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            version_number=version_number,
            predecessor_version_id=current.id if current is not None else None,
            file_name=source.file_name,
            content_type=source.content_type,
            storage_key=source.storage_key,
            checksum=source.checksum,
            byte_size=source.byte_size,
            uploaded_by=principal.user_id,
            uploaded_at=now,
            processing_state="pending",
            processing_job_id=None,
            extraction_version=None,
            analysis_provenance={},
            idempotency_key=idempotency_key,
        )
        created = self._repository.create_version(
            record,
            actor_id=principal.user_id,
            action="version_created",
        )
        metadata = dict(agreement.audit_metadata)
        metadata.pop("processing_job_id", None)
        self._repository.replace(
            agreement.model_copy(
                update={
                    "files": [source],
                    "current_version_id": created.id,
                    "comparison_baseline_version_id": current.id if current else None,
                    "processing_state": "pending",
                    "audit_metadata": metadata,
                    "updated_at": now,
                }
            )
        )
        self._identity.session.commit()
        return created, True

    def authorize_upload(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_UPDATE,
        ):
            raise AgreementNotFoundError
        self._agreements.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )

    @staticmethod
    def _in_scope(
        version: AgreementVersionRecord,
        *,
        agreement_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
    ) -> bool:
        return (
            version.agreement_id == agreement_id
            and version.organization_id == organization_id
            and version.workspace_id == workspace_id
        )
