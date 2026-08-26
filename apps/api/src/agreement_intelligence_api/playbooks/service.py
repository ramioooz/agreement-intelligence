from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from agreement_intelligence_api.agreements.access import active_agreement_statement
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.playbooks.models import (
    LegalPlaybookRecord,
    PlaybookAuditEventRecord,
    PlaybookRuleRecord,
    PlaybookVersionRecord,
)
from agreement_intelligence_api.playbooks.schemas import (
    CreatePlaybookRequest,
    CreatePlaybookVersionRequest,
    DocumentDirection,
    PlaybookAuditEventResponse,
    PlaybookOverrideRequest,
    PlaybookRuleResponse,
    PlaybookRuleWrite,
    PlaybookStatus,
    PlaybookVersionResponse,
    PolicyType,
    RuleEvaluationConfig,
    Severity,
    UpdatePlaybookRuleRequest,
)


class PlaybookService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def create(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: CreatePlaybookRequest,
    ) -> PlaybookVersionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        playbook = LegalPlaybookRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=request.name,
            agreement_family=request.agreement_family,
            document_direction=request.document_direction,
            jurisdiction=request.jurisdiction.upper(),
            priority=request.priority,
            created_by=principal.user_id,
        )
        self._session.add(playbook)
        self._session.flush()
        version = PlaybookVersionRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            playbook_id=playbook.id,
            version=1,
            status="draft",
            created_by=principal.user_id,
        )
        self._session.add(version)
        self._session.flush()
        for rule in request.rules:
            self._add_rule_record(version, rule)
        self._audit(
            playbook=playbook,
            version=version,
            actor_id=principal.user_id,
            action="draft_created",
        )
        response = self._response(version, playbook)
        self._session.commit()
        return response

    def create_version(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        request: CreatePlaybookVersionRequest,
    ) -> PlaybookVersionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        for attempt in range(2):
            try:
                self._identity.scope_organization(organization_id)
                playbook = self._playbook_for_scope(
                    playbook_id,
                    organization_id,
                    workspace_id,
                    lock_for_update=True,
                )
                source_version = None
                if request.source_version is not None:
                    source_version = self._version_for_scope(
                        playbook_id, request.source_version, organization_id, workspace_id
                    )
                next_version = (
                    self._session.scalar(
                        select(func.coalesce(func.max(PlaybookVersionRecord.version), 0) + 1).where(
                            PlaybookVersionRecord.playbook_id == playbook_id
                        )
                    )
                    or 1
                )
                version = PlaybookVersionRecord(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    playbook_id=playbook_id,
                    version=next_version,
                    status="draft",
                    created_by=principal.user_id,
                )
                self._session.add(version)
                self._session.flush()
                if source_version is not None:
                    for source_rule in source_version.rules:
                        self._session.add(
                            PlaybookRuleRecord(
                                organization_id=organization_id,
                                workspace_id=workspace_id,
                                playbook_version_id=version.id,
                                clause_type=source_rule.clause_type,
                                title=source_rule.title,
                                policy_type=source_rule.policy_type,
                                preferred_language=source_rule.preferred_language,
                                fallback_language=source_rule.fallback_language,
                                severity=source_rule.severity,
                                legal_rationale=source_rule.legal_rationale,
                                reviewer_guidance=source_rule.reviewer_guidance,
                                evaluation_config=source_rule.evaluation_config,
                            )
                        )
                self._session.flush()
                self._audit(
                    playbook=playbook,
                    version=version,
                    actor_id=principal.user_id,
                    action="draft_created",
                )
                response = self._response(version, playbook)
                self._session.commit()
                return response
            except IntegrityError as error:
                self._session.rollback()
                if attempt == 0 and _is_playbook_version_conflict(error):
                    continue
                if _is_playbook_version_conflict(error):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"code": "playbook_version_conflict"},
                    ) from error
                raise
        raise RuntimeError("playbook version creation retry loop exhausted")

    def override_for_agreement(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: PlaybookOverrideRequest,
    ) -> PlaybookVersionResponse:
        self._authorize_override(
            principal, organization_id=organization_id, workspace_id=workspace_id
        )
        agreement = self._session.scalar(
            active_agreement_statement(
                request.agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                for_update=True,
            )
        )
        if agreement is None:
            hide_resource()
        version = self._session.scalar(
            select(PlaybookVersionRecord)
            .options(selectinload(PlaybookVersionRecord.playbook))
            .where(PlaybookVersionRecord.id == request.playbook_version_id)
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
            .where(PlaybookVersionRecord.status == "published")
        )
        if version is None or version.playbook.archived_at is not None:
            hide_resource()
        if version.playbook.agreement_family != agreement.agreement_type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "playbook_override_family_mismatch"},
            )
        self._audit(
            playbook=version.playbook,
            version=version,
            actor_id=principal.user_id,
            action="agreement_override_recorded",
            agreement_id=agreement.id,
            metadata={"reason": request.reason},
        )
        response = self._response(version, version.playbook)
        self._session.commit()
        return response

    def eligible_for_agreement(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> list[PlaybookVersionResponse]:
        self._authorize_override(
            principal, organization_id=organization_id, workspace_id=workspace_id
        )
        agreement = self._session.scalar(
            active_agreement_statement(
                agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                for_update=True,
            )
        )
        if agreement is None:
            hide_resource()
        versions = self._session.scalars(
            select(PlaybookVersionRecord)
            .join(PlaybookVersionRecord.playbook)
            .options(selectinload(PlaybookVersionRecord.rules))
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
            .where(PlaybookVersionRecord.status == "published")
            .where(LegalPlaybookRecord.archived_at.is_(None))
            .where(LegalPlaybookRecord.agreement_family == agreement.agreement_type)
            .order_by(LegalPlaybookRecord.priority.desc(), PlaybookVersionRecord.id)
        )
        return [self._response(version, version.playbook) for version in versions]

    def add_rule(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        version_number: int,
        request: PlaybookRuleWrite,
    ) -> PlaybookVersionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        version = self._version_for_scope(
            playbook_id, version_number, organization_id, workspace_id
        )
        self._ensure_draft(version)
        rule = self._add_rule_record(version, request)
        self._audit(
            playbook=version.playbook,
            version=version,
            rule=rule,
            actor_id=principal.user_id,
            action="rule_created",
        )
        response = self._response(version, version.playbook)
        self._session.commit()
        return response

    def update_rule(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        version_number: int,
        rule_id: UUID,
        request: UpdatePlaybookRuleRequest,
    ) -> PlaybookVersionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        version = self._version_for_scope(
            playbook_id, version_number, organization_id, workspace_id
        )
        self._ensure_draft(version)
        rule = self._session.scalar(
            select(PlaybookRuleRecord)
            .where(PlaybookRuleRecord.id == rule_id)
            .where(PlaybookRuleRecord.playbook_version_id == version.id)
            .where(PlaybookRuleRecord.organization_id == organization_id)
            .where(PlaybookRuleRecord.workspace_id == workspace_id)
        )
        if rule is None:
            hide_resource()
        for field, value in request.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
        rule.updated_at = datetime.now(UTC)
        self._audit(
            playbook=version.playbook,
            version=version,
            rule=rule,
            actor_id=principal.user_id,
            action="rule_updated",
        )
        response = self._response(version, version.playbook)
        self._session.commit()
        return response

    def delete_rule(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        version_number: int,
        rule_id: UUID,
        confirmed: bool,
    ) -> None:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        if not confirmed:
            self._confirmation_required()
        version = self._version_for_scope(
            playbook_id, version_number, organization_id, workspace_id
        )
        self._ensure_draft(version)
        rule = self._session.scalar(
            select(PlaybookRuleRecord)
            .where(PlaybookRuleRecord.id == rule_id)
            .where(PlaybookRuleRecord.playbook_version_id == version.id)
        )
        if rule is None:
            hide_resource()
        self._audit(
            playbook=version.playbook,
            version=version,
            rule=rule,
            actor_id=principal.user_id,
            action="rule_deleted",
        )
        self._session.delete(rule)
        self._session.commit()

    def publish(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        version_number: int,
    ) -> PlaybookVersionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        version = self._version_for_scope(
            playbook_id, version_number, organization_id, workspace_id
        )
        self._ensure_draft(version)
        self._validate_for_publication(version)
        published_version = self._session.scalar(
            select(PlaybookVersionRecord.id)
            .where(PlaybookVersionRecord.playbook_id == playbook_id)
            .where(PlaybookVersionRecord.status == "published")
        )
        if published_version is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "published_playbook_exists"},
            )
        routing_conflict = self._session.scalar(
            select(PlaybookVersionRecord.id)
            .join(PlaybookVersionRecord.playbook)
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
            .where(PlaybookVersionRecord.status == "published")
            .where(PlaybookVersionRecord.playbook_id != playbook_id)
            .where(LegalPlaybookRecord.archived_at.is_(None))
            .where(LegalPlaybookRecord.agreement_family == version.playbook.agreement_family)
            .where(LegalPlaybookRecord.document_direction == version.playbook.document_direction)
            .where(LegalPlaybookRecord.jurisdiction == version.playbook.jurisdiction)
            .where(LegalPlaybookRecord.priority == version.playbook.priority)
        )
        if routing_conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "playbook_routing_conflict"},
            )
        version.status = "published"
        version.published_at = datetime.now(UTC)
        self._audit(
            playbook=version.playbook,
            version=version,
            actor_id=principal.user_id,
            action="published",
        )
        response = self._response(version, version.playbook)
        self._session.commit()
        return response

    def delete_version(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        version_number: int,
        confirmed: bool,
        reason: str | None,
    ) -> None:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        if not confirmed:
            self._confirmation_required()
        version = self._version_for_scope(
            playbook_id, version_number, organization_id, workspace_id
        )
        self._ensure_draft(version)
        self._audit(
            playbook=version.playbook,
            version=version,
            actor_id=principal.user_id,
            action="draft_deleted",
            metadata=_reason_metadata(reason),
        )
        self._session.delete(version)
        self._session.commit()

    def archive(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        reason: str | None,
    ) -> PlaybookVersionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        playbook = self._playbook_for_scope(playbook_id, organization_id, workspace_id)
        has_draft = self._session.scalar(
            select(PlaybookVersionRecord.id)
            .where(PlaybookVersionRecord.playbook_id == playbook.id)
            .where(PlaybookVersionRecord.status == "draft")
            .limit(1)
        )
        if has_draft is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "draft_playbook_version_must_be_deleted"},
            )
        if playbook.archived_at is None:
            playbook.archived_at = datetime.now(UTC)
            versions = list(playbook.versions)
            for version in versions:
                self._audit(
                    playbook=playbook,
                    version=version,
                    actor_id=principal.user_id,
                    action="archived",
                    metadata=_reason_metadata(reason),
                )
            self._session.flush()
            version = max(versions, key=lambda item: item.version)
            response = self._response(version, playbook)
            self._session.commit()
            return response
        latest_version = self._session.scalar(
            select(PlaybookVersionRecord)
            .where(PlaybookVersionRecord.playbook_id == playbook.id)
            .order_by(PlaybookVersionRecord.version.desc())
        )
        if latest_version is None:
            raise RuntimeError("persisted playbook has no versions")
        return self._response(latest_version, playbook)

    def delete_playbook(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        playbook_id: UUID,
        confirmed: bool,
        reason: str | None,
    ) -> None:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        if not confirmed:
            self._confirmation_required()
        playbook = self._playbook_for_scope(playbook_id, organization_id, workspace_id)
        versions = list(
            self._session.scalars(
                select(PlaybookVersionRecord)
                .where(PlaybookVersionRecord.playbook_id == playbook.id)
                .where(PlaybookVersionRecord.organization_id == organization_id)
                .where(PlaybookVersionRecord.workspace_id == workspace_id)
            )
        )
        if any(version.status == "published" for version in versions):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "published_playbook_must_be_archived"},
            )
        for version in versions:
            self._audit(
                playbook=playbook,
                version=version,
                actor_id=principal.user_id,
                action="draft_deleted",
                metadata=_reason_metadata(reason),
            )
        version_ids = [version.id for version in versions]
        if version_ids:
            self._session.execute(
                delete(PlaybookRuleRecord).where(
                    PlaybookRuleRecord.playbook_version_id.in_(version_ids)
                )
            )
            self._session.execute(
                delete(PlaybookVersionRecord).where(PlaybookVersionRecord.id.in_(version_ids))
            )
        self._session.execute(
            delete(LegalPlaybookRecord).where(LegalPlaybookRecord.id == playbook.id)
        )
        self._session.commit()

    def list(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_family: str | None,
        include_archived: bool,
    ) -> list[PlaybookVersionResponse]:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        statement = (
            select(PlaybookVersionRecord)
            .join(PlaybookVersionRecord.playbook)
            .options(selectinload(PlaybookVersionRecord.rules))
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
            .order_by(PlaybookVersionRecord.playbook_id, PlaybookVersionRecord.version)
        )
        if not include_archived:
            statement = statement.where(LegalPlaybookRecord.archived_at.is_(None))
        if agreement_family is not None:
            statement = statement.where(LegalPlaybookRecord.agreement_family == agreement_family)
        return [
            self._response(version, version.playbook)
            for version in self._session.scalars(statement)
        ]

    def _authorize(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        allowed = self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.PLAYBOOKS_MANAGE,
        )
        if not allowed:
            hide_resource()

    def _authorize_override(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        allowed = self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.REVIEWS_APPROVE,
        )
        if not allowed:
            hide_resource()

    def _playbook_for_scope(
        self,
        playbook_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        *,
        lock_for_update: bool = False,
    ) -> LegalPlaybookRecord:
        statement = (
            select(LegalPlaybookRecord)
            .where(LegalPlaybookRecord.id == playbook_id)
            .where(LegalPlaybookRecord.organization_id == organization_id)
            .where(LegalPlaybookRecord.workspace_id == workspace_id)
        )
        if lock_for_update:
            statement = statement.with_for_update()
        playbook = self._session.scalar(statement)
        if playbook is None:
            hide_resource()
        return playbook

    def _version_for_scope(
        self, playbook_id: UUID, version_number: int, organization_id: UUID, workspace_id: UUID
    ) -> PlaybookVersionRecord:
        version = self._session.scalar(
            select(PlaybookVersionRecord)
            .options(
                selectinload(PlaybookVersionRecord.rules),
                selectinload(PlaybookVersionRecord.playbook),
            )
            .where(PlaybookVersionRecord.playbook_id == playbook_id)
            .where(PlaybookVersionRecord.version == version_number)
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
        )
        if version is None:
            hide_resource()
        return version

    @staticmethod
    def _ensure_draft(version: PlaybookVersionRecord) -> None:
        if version.status == "published":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "published_playbook_immutable"},
            )

    def _validate_for_publication(self, version: PlaybookVersionRecord) -> None:
        if not version.rules:
            self._invalid_draft("at least one playbook rule is required")
        normalized_clause_types = [rule.clause_type.strip().casefold() for rule in version.rules]
        if len(set(normalized_clause_types)) != len(normalized_clause_types):
            self._invalid_draft("playbook version contains duplicate clause types")
        for rule in version.rules:
            if (
                not rule.title.strip()
                or not rule.legal_rationale.strip()
                or not rule.reviewer_guidance.strip()
            ):
                self._invalid_draft("title, legal rationale, and reviewer guidance are required")
            if (
                rule.policy_type in {"required", "preferred"}
                and not (rule.preferred_language or "").strip()
            ):
                self._invalid_draft(f"preferred language is required for {rule.policy_type} rules")

    @staticmethod
    def _invalid_draft(message: str) -> None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_playbook_draft", "message": message},
        )

    @staticmethod
    def _confirmation_required() -> None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "deletion_confirmation_required"},
        )

    def _add_rule_record(
        self, version: PlaybookVersionRecord, rule: PlaybookRuleWrite
    ) -> PlaybookRuleRecord:
        record = PlaybookRuleRecord(
            organization_id=version.organization_id,
            workspace_id=version.workspace_id,
            playbook_version_id=version.id,
            **rule.model_dump(exclude={"evaluation_config"}),
            evaluation_config=rule.evaluation_config.model_dump(),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def _audit(
        self,
        *,
        playbook: LegalPlaybookRecord,
        version: PlaybookVersionRecord,
        actor_id: UUID,
        action: str,
        rule: PlaybookRuleRecord | None = None,
        metadata: dict[str, object] | None = None,
        agreement_id: UUID | None = None,
    ) -> None:
        self._session.add(
            PlaybookAuditEventRecord(
                organization_id=playbook.organization_id,
                workspace_id=playbook.workspace_id,
                playbook_id=playbook.id,
                playbook_version_id=version.id,
                playbook_rule_id=rule.id if rule else None,
                agreement_id=agreement_id,
                action=action,
                actor_id=actor_id,
                metadata_json={"version": version.version, **(metadata or {})},
                occurred_at=datetime.now(UTC),
            )
        )
        self._session.flush()

    def _response(
        self, version: PlaybookVersionRecord, playbook: LegalPlaybookRecord
    ) -> PlaybookVersionResponse:
        audit_events = list(
            self._session.scalars(
                select(PlaybookAuditEventRecord)
                .where(PlaybookAuditEventRecord.playbook_version_id == version.id)
                .order_by(PlaybookAuditEventRecord.occurred_at, PlaybookAuditEventRecord.id)
            )
        )
        return PlaybookVersionResponse(
            id=version.id,
            playbook_id=playbook.id,
            organization_id=version.organization_id,
            workspace_id=version.workspace_id,
            name=playbook.name,
            version=version.version,
            status=cast(PlaybookStatus, "archived" if playbook.archived_at else version.status),
            agreement_family=playbook.agreement_family,
            document_direction=cast(DocumentDirection, playbook.document_direction),
            jurisdiction=playbook.jurisdiction,
            priority=playbook.priority,
            rules=[
                PlaybookRuleResponse(
                    id=rule.id,
                    clause_type=rule.clause_type,
                    title=rule.title,
                    policy_type=cast(PolicyType, rule.policy_type),
                    preferred_language=rule.preferred_language,
                    fallback_language=rule.fallback_language,
                    severity=cast(Severity, rule.severity),
                    legal_rationale=rule.legal_rationale,
                    reviewer_guidance=rule.reviewer_guidance,
                    evaluation_config=RuleEvaluationConfig.model_validate(rule.evaluation_config),
                )
                for rule in version.rules
            ],
            audit_events=[
                PlaybookAuditEventResponse(
                    action=event.action,
                    actor_id=str(event.actor_id),
                    occurred_at=_required_aware_utc(event.occurred_at),
                    metadata=event.metadata_json,
                )
                for event in audit_events
            ],
            created_at=_required_aware_utc(version.created_at),
            published_at=_as_aware_utc(version.published_at),
            archived_at=_as_aware_utc(playbook.archived_at),
        )


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _reason_metadata(reason: str | None) -> dict[str, object]:
    return {"reason": reason} if reason else {}


def _required_aware_utc(value: datetime | None) -> datetime:
    if value is None:
        raise RuntimeError("persisted timestamp is missing")
    return cast(datetime, _as_aware_utc(value))


def _is_playbook_version_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return constraint_name == "uq_playbook_versions_playbook_version" or (
        "playbook_versions.playbook_id, playbook_versions.version" in str(error.orig)
    )
