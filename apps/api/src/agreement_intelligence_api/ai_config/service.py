from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agreement_intelligence_api.ai_config.models import (
    AIConfigurationAuditEventRecord,
    AIConfigurationPromotionRecord,
    AIConfigurationVersionRecord,
)
from agreement_intelligence_api.ai_config.schemas import (
    AIConfigurationPromotionResponse,
    AIConfigurationResponse,
    AIOperation,
    CreateAIConfigurationRequest,
)
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService


class AIConfigurationService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def create(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: CreateAIConfigurationRequest,
    ) -> AIConfigurationResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        record = AIConfigurationVersionRecord(
            operation=request.operation.value,
            version=request.version,
            prompt_template=request.prompt_template,
            prompt_checksum=_checksum(request.prompt_template),
            schema_json=request.schema_definition,
            schema_checksum=_checksum(_canonical_json(request.schema_definition)),
            model_route=request.model_route,
            parameters_json=request.parameters,
            status="draft",
            created_by=principal.user_id,
        )
        self._session.add(record)
        try:
            self._session.flush()
        except IntegrityError as error:
            self._session.rollback()
            if _is_duplicate_configuration(error):
                raise _conflict("ai_configuration_version_conflict") from error
            raise
        self._audit(record, principal.user_id, "draft_created")
        response = _response(record)
        self._session.commit()
        return response

    def validate(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        configuration_id: UUID,
    ) -> AIConfigurationResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        record = self._record(configuration_id)
        self._ensure_valid(record)
        return _response(record)

    def publish(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        configuration_id: UUID,
    ) -> AIConfigurationResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        record = self._record(configuration_id)
        self._ensure_draft(record)
        self._ensure_valid(record)
        record.status = "published"
        record.published_at = datetime.now(UTC)
        self._audit(record, principal.user_id, "published")
        response = _response(record)
        self._session.commit()
        return response

    def promote(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        configuration_id: UUID,
        environment: str,
    ) -> AIConfigurationPromotionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        record = self._record(configuration_id)
        if record.status != "published":
            raise _conflict("ai_configuration_not_published")
        promotion = AIConfigurationPromotionRecord(
            configuration_id=record.id,
            operation=record.operation,
            environment=environment,
            promoted_by=principal.user_id,
        )
        self._session.add(promotion)
        self._session.flush()
        self._audit(record, principal.user_id, "promoted", environment=environment)
        response = _promotion_response(promotion)
        self._session.commit()
        return response

    def resolve(
        self, *, operation: str, environment: str, configuration_id: UUID | None = None
    ) -> AIConfigurationResponse | None:
        if configuration_id is not None:
            record = self._session.scalar(
                select(AIConfigurationVersionRecord)
                .where(AIConfigurationVersionRecord.id == configuration_id)
                .where(AIConfigurationVersionRecord.operation == operation)
            )
            return _response(record) if record is not None else None
        record = self._session.scalar(
            select(AIConfigurationVersionRecord)
            .join(
                AIConfigurationPromotionRecord,
                AIConfigurationPromotionRecord.configuration_id == AIConfigurationVersionRecord.id,
            )
            .where(AIConfigurationPromotionRecord.operation == operation)
            .where(AIConfigurationPromotionRecord.environment == environment)
            .where(AIConfigurationVersionRecord.status == "published")
            .order_by(
                AIConfigurationPromotionRecord.promoted_at.desc(),
                AIConfigurationPromotionRecord.id.desc(),
            )
        )
        return _response(record) if record is not None else None

    def get(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        configuration_id: UUID,
    ) -> AIConfigurationResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        return _response(self._record(configuration_id))

    def list(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> list[AIConfigurationResponse]:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        statement = select(AIConfigurationVersionRecord).order_by(
            AIConfigurationVersionRecord.operation,
            AIConfigurationVersionRecord.version,
        )
        return [_response(record) for record in self._session.scalars(statement)]

    def update_prompt(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        configuration_id: UUID,
        prompt_template: str,
    ) -> AIConfigurationResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        record = self._record(configuration_id)
        self._ensure_draft(record)
        record.prompt_template = prompt_template
        record.prompt_checksum = _checksum(prompt_template)
        response = _response(record)
        self._session.commit()
        return response

    def _authorize(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.PLAYBOOKS_MANAGE,
        ):
            hide_resource()

    def _record(self, configuration_id: UUID) -> AIConfigurationVersionRecord:
        record = self._session.get(AIConfigurationVersionRecord, configuration_id)
        if record is None:
            hide_resource()
        return record

    @staticmethod
    def _ensure_draft(record: AIConfigurationVersionRecord) -> None:
        if record.status != "draft":
            raise _conflict("published_ai_configuration_immutable")

    @staticmethod
    def _ensure_valid(record: AIConfigurationVersionRecord) -> None:
        if (
            not record.prompt_template.strip()
            or not record.schema_json
            or not record.model_route.strip()
            or record.prompt_checksum != _checksum(record.prompt_template)
            or record.schema_checksum != _checksum(_canonical_json(record.schema_json))
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_ai_configuration_draft"},
            )

    def _audit(
        self,
        record: AIConfigurationVersionRecord,
        actor_id: UUID,
        action: str,
        *,
        environment: str | None = None,
    ) -> None:
        metadata: dict[str, str] = {
            "operation": record.operation,
            "version": record.version,
            "prompt_checksum": record.prompt_checksum,
            "schema_checksum": record.schema_checksum,
        }
        if environment is not None:
            metadata["environment"] = environment
        self._session.add(
            AIConfigurationAuditEventRecord(
                configuration_id=record.id,
                actor_id=actor_id,
                action=action,
                metadata_json=metadata,
            )
        )


def _response(record: AIConfigurationVersionRecord) -> AIConfigurationResponse:
    return AIConfigurationResponse.model_validate(
        {
            "id": record.id,
            "operation": AIOperation(record.operation),
            "version": record.version,
            "prompt_template": record.prompt_template,
            "prompt_checksum": record.prompt_checksum,
            "schema": record.schema_json,
            "schema_checksum": record.schema_checksum,
            "model_route": record.model_route,
            "parameters": record.parameters_json,
            "status": record.status,
            "created_by": record.created_by,
            "created_at": record.created_at,
            "published_at": record.published_at,
        }
    )


def _promotion_response(record: AIConfigurationPromotionRecord) -> AIConfigurationPromotionResponse:
    return AIConfigurationPromotionResponse(
        id=record.id,
        configuration_id=record.configuration_id,
        operation=AIOperation(record.operation),
        environment=record.environment,
        promoted_by=record.promoted_by,
        promoted_at=record.promoted_at,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _is_duplicate_configuration(error: IntegrityError) -> bool:
    return "ai_configuration_versions.operation, ai_configuration_versions.version" in str(
        error.orig
    )


def _conflict(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code})
