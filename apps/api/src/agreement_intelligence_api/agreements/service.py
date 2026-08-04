from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agreement_intelligence_api.agreements.models import AgreementVersionRecord
from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.schemas import (
    AgreementListResponse,
    AgreementPage,
    AgreementResponse,
    AuditEvent,
    CreateAgreementRequest,
)
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService


class AgreementNotFoundError(Exception):
    pass


class AgreementService:
    def __init__(
        self,
        repository: SQLAlchemyAgreementRepository,
        identity: IdentityService,
    ) -> None:
        self._repository = repository
        self._identity = identity

    def create(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: CreateAgreementRequest,
    ) -> AgreementResponse:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_CREATE,
        )
        now = datetime.now(UTC)
        agreement = AgreementResponse(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            title=request.title,
            agreement_type=request.agreement_type,
            status=request.status,
            parties=request.parties,
            files=request.files,
            processing_state=request.processing_state,
            audit_metadata=request.audit_metadata,
            audit_events=[
                AuditEvent(action="created", actor_id=str(principal.user_id), occurred_at=now),
            ],
            archived_at=None,
            created_at=now,
            updated_at=now,
        )
        created = self._repository.create(agreement)
        if created.files:
            source = created.files[-1]
            initial = AgreementVersionRecord(
                id=uuid4(),
                agreement_id=created.id,
                organization_id=created.organization_id,
                workspace_id=created.workspace_id,
                version_number=1,
                predecessor_version_id=None,
                file_name=source.file_name,
                content_type=source.content_type,
                storage_key=source.storage_key,
                checksum=source.checksum,
                byte_size=source.byte_size,
                uploaded_by=principal.user_id,
                uploaded_at=now,
                processing_state=created.processing_state,
                processing_job_id=None,
                extraction_version=None,
                analysis_provenance={},
                idempotency_key=f"initial:{created.id}",
            )
            version = self._repository.create_version(
                initial,
                actor_id=principal.user_id,
                action="version_created",
            )
            created = self._repository.replace(
                created.model_copy(update={"current_version_id": version.id})
            )
        self._identity.session.commit()
        return created

    def get(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> AgreementResponse:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_READ,
        )
        agreement = self._repository.get(agreement_id)
        if agreement is None or not self._is_visible_to(
            agreement,
            organization_id=organization_id,
            workspace_id=workspace_id,
        ):
            raise AgreementNotFoundError
        return agreement

    def list(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        limit: int,
        cursor: int,
        query: str | None,
        agreement_type: str | None,
        status: str | None,
        include_archived: bool,
    ) -> AgreementListResponse:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_READ,
        )
        agreements = self._repository.list_for_scope(
            organization_id,
            workspace_id,
            query=query,
            agreement_type=agreement_type,
            status=status,
            include_archived=include_archived,
        )
        items = agreements[cursor : cursor + limit]
        next_offset = cursor + len(items)
        next_cursor = str(next_offset) if next_offset < len(agreements) else None
        return AgreementListResponse(
            items=items,
            page=AgreementPage(limit=limit, next_cursor=next_cursor),
        )

    def archive(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> AgreementResponse:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_UPDATE,
        )
        agreement = self.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        if agreement.archived_at is not None:
            return agreement
        now = datetime.now(UTC)
        archived = agreement.model_copy(
            update={
                "archived_at": now,
                "updated_at": now,
                "audit_events": [
                    *agreement.audit_events,
                    AuditEvent(action="archived", actor_id=str(principal.user_id), occurred_at=now),
                ],
            },
        )
        replaced = self._repository.replace(archived)
        self._identity.session.commit()
        return replaced

    def restore(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> AgreementResponse:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_UPDATE,
        )
        agreement = self.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        if agreement.archived_at is None:
            return agreement
        now = datetime.now(UTC)
        restored = agreement.model_copy(
            update={
                "archived_at": None,
                "updated_at": now,
                "audit_events": [
                    *agreement.audit_events,
                    AuditEvent(action="restored", actor_id=str(principal.user_id), occurred_at=now),
                ],
            },
        )
        replaced = self._repository.replace(restored)
        self._identity.session.commit()
        return replaced

    def permanently_delete(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> AgreementResponse:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_DELETE,
        )
        agreement = self.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        self._repository.permanently_delete(agreement, actor_id=principal.user_id)
        self._identity.session.commit()
        return agreement

    def deletion_object_keys(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> tuple[AgreementResponse, Sequence[str]]:
        self._authorize(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_DELETE,
        )
        agreement = self.get(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
        )
        return agreement, self._repository.deletion_object_keys(agreement)

    def _authorize(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        permission: PermissionKey,
    ) -> None:
        allowed = self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=permission,
        )
        if not allowed:
            raise AgreementNotFoundError

    @staticmethod
    def _is_visible_to(
        agreement: AgreementResponse,
        *,
        organization_id: UUID,
        workspace_id: UUID,
    ) -> bool:
        return (
            agreement.organization_id == organization_id and agreement.workspace_id == workspace_id
        )
