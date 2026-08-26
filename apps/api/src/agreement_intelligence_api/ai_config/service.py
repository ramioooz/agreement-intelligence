from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from jsonschema.validators import validator_for  # type: ignore[import-untyped]
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.models import AgreementRecord
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
from agreement_intelligence_api.processing.models import (
    ProcessingJobRecord,
    ProcessingOutboxRecord,
)
from agreement_intelligence_api.processing.queue import (
    LoggingProcessingQueuePublisher,
    ProcessingOutboxDispatcher,
    ProcessingQueuePublisher,
)
from agreement_intelligence_api.retrieval.models import RetrievalIndexBuildRecord


class AIConfigurationService:
    def __init__(
        self,
        session: Session,
        identity: IdentityService,
        *,
        queue: ProcessingQueuePublisher | None = None,
    ) -> None:
        self._session = session
        self._identity = identity
        self._queue = queue or LoggingProcessingQueuePublisher()

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
            organization_id=organization_id,
            workspace_id=workspace_id,
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
        record = self._record(configuration_id, organization_id, workspace_id)
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
        record = self._record(configuration_id, organization_id, workspace_id)
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
        record = self._record(configuration_id, organization_id, workspace_id)
        if record.status != "published":
            raise _conflict("ai_configuration_not_published")
        self._ensure_valid(record)
        promotion = AIConfigurationPromotionRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            configuration_id=record.id,
            operation=record.operation,
            environment=environment,
            promoted_by=principal.user_id,
        )
        self._session.add(promotion)
        self._session.flush()
        reindex_jobs = self._enqueue_embedding_reindex_jobs(
            record,
            environment=environment,
        )
        self._audit(
            record,
            principal.user_id,
            "promoted",
            environment=environment,
            reindex_job_count=reindex_jobs,
        )
        response = _promotion_response(promotion)
        self._session.commit()
        if record.operation == AIOperation.EMBEDDING.value and environment == os.environ.get(
            "AI_CONFIGURATION_ENVIRONMENT", "local"
        ):
            ProcessingOutboxDispatcher(
                session=self._session, publisher=self._queue
            ).dispatch_pending(
                organization_id=organization_id,
                workspace_id=workspace_id,
                limit=max(10_000, reindex_jobs),
            )
        return response

    def resolve(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        operation: str,
        environment: str,
        configuration_id: UUID | None = None,
    ) -> AIConfigurationResponse | None:
        if configuration_id is not None:
            record = self._session.scalar(
                select(AIConfigurationVersionRecord)
                .where(AIConfigurationVersionRecord.id == configuration_id)
                .where(AIConfigurationVersionRecord.organization_id == organization_id)
                .where(AIConfigurationVersionRecord.workspace_id == workspace_id)
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
            .where(AIConfigurationPromotionRecord.organization_id == organization_id)
            .where(AIConfigurationPromotionRecord.workspace_id == workspace_id)
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
        return _response(self._record(configuration_id, organization_id, workspace_id))

    def list(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> list[AIConfigurationResponse]:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        statement = (
            select(AIConfigurationVersionRecord)
            .where(
                AIConfigurationVersionRecord.organization_id == organization_id,
                AIConfigurationVersionRecord.workspace_id == workspace_id,
            )
            .order_by(
                AIConfigurationVersionRecord.operation,
                AIConfigurationVersionRecord.version,
            )
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
        record = self._record(configuration_id, organization_id, workspace_id)
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

    def _record(
        self, configuration_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> AIConfigurationVersionRecord:
        record = self._session.scalar(
            select(AIConfigurationVersionRecord)
            .where(AIConfigurationVersionRecord.id == configuration_id)
            .where(AIConfigurationVersionRecord.organization_id == organization_id)
            .where(AIConfigurationVersionRecord.workspace_id == workspace_id)
        )
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
        try:
            schema_validator = validator_for(record.schema_json)
            schema_validator.check_schema(record.schema_json)
        except SchemaError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_ai_configuration_schema"},
            ) from error
        if not _supported_runtime_configuration(record):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "unsupported_ai_configuration"},
            )

    def _audit(
        self,
        record: AIConfigurationVersionRecord,
        actor_id: UUID,
        action: str,
        *,
        environment: str | None = None,
        reindex_job_count: int | None = None,
    ) -> None:
        metadata: dict[str, str] = {
            "operation": record.operation,
            "version": record.version,
            "prompt_checksum": record.prompt_checksum,
            "schema_checksum": record.schema_checksum,
        }
        if environment is not None:
            metadata["environment"] = environment
        if reindex_job_count is not None:
            metadata["reindex_job_count"] = str(reindex_job_count)
        self._session.add(
            AIConfigurationAuditEventRecord(
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                configuration_id=record.id,
                actor_id=actor_id,
                action=action,
                metadata_json=metadata,
            )
        )

    def _enqueue_embedding_reindex_jobs(
        self,
        record: AIConfigurationVersionRecord,
        *,
        environment: str,
    ) -> int:
        if record.operation != AIOperation.EMBEDDING.value or environment != os.environ.get(
            "AI_CONFIGURATION_ENVIRONMENT", "local"
        ):
            return 0
        profile = f"embedding-reindex:{record.id}"
        now = datetime.now(UTC)
        indexed_agreements = self._session.execute(
            select(RetrievalIndexBuildRecord, AgreementRecord)
            .join(
                AgreementRecord,
                and_(
                    AgreementRecord.id == RetrievalIndexBuildRecord.agreement_id,
                    AgreementRecord.organization_id == RetrievalIndexBuildRecord.organization_id,
                    AgreementRecord.workspace_id == RetrievalIndexBuildRecord.workspace_id,
                ),
            )
            .where(
                RetrievalIndexBuildRecord.organization_id == record.organization_id,
                RetrievalIndexBuildRecord.workspace_id == record.workspace_id,
                RetrievalIndexBuildRecord.state == "active",
                AgreementRecord.archived_at.is_(None),
                AgreementRecord.deletion_requested_at.is_(None),
            )
        ).all()
        created = 0
        for build, agreement in indexed_agreements:
            idempotency_key = f"ai-config:{record.id}:embedding-reindex:{build.id}"
            existing = self._session.scalar(
                select(ProcessingJobRecord).where(
                    ProcessingJobRecord.agreement_id == agreement.id,
                    ProcessingJobRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                continue
            job = ProcessingJobRecord(
                id=uuid4(),
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                agreement_id=agreement.id,
                version_id=None,
                idempotency_key=idempotency_key,
                profile=profile,
                source_storage_key=None,
                source_checksum=build.source_checksum,
                source_content_type=None,
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
            self._session.add(job)
            self._session.flush()
            self._session.add(
                ProcessingOutboxRecord(
                    job_id=job.id,
                    organization_id=job.organization_id,
                    workspace_id=job.workspace_id,
                    agreement_id=job.agreement_id,
                    idempotency_key=idempotency_key,
                    profile=profile,
                    attempt_count=0,
                    queued_at=now,
                    delivered_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        return created


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
    return "ai_configuration_versions" in str(error.orig) and "operation" in str(error.orig)


def _supported_runtime_configuration(record: AIConfigurationVersionRecord) -> bool:
    provider, separator, model = record.model_route.partition(":")
    if separator != ":" or provider not in {"openai", "openai-compatible"} or not model.strip():
        return False
    parameters = record.parameters_json
    if record.operation == AIOperation.EMBEDDING.value:
        if set(parameters) - {"encoding_format"}:
            return False
        encoding_format = parameters.get("encoding_format")
        return encoding_format is None or encoding_format in {"float", "base64"}
    allowed = (
        {"temperature", "max_output_tokens"}
        if provider == "openai"
        else {"temperature", "max_tokens"}
    )
    if set(parameters) - allowed:
        return False
    temperature = parameters.get("temperature")
    if temperature is not None and (
        isinstance(temperature, bool) or not isinstance(temperature, int | float)
    ):
        return False
    for name in {"max_output_tokens", "max_tokens"} & set(parameters):
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return False
    return True


def _conflict(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code})
