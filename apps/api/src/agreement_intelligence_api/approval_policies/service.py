from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from agreement_intelligence_api.approval_policies.models import (
    ApprovalPolicyAuditEventRecord,
    ApprovalPolicyRecord,
    ApprovalPolicyStageRecord,
    ApprovalPolicyVersionRecord,
)
from agreement_intelligence_api.approval_policies.schemas import (
    ApprovalMode,
    ApprovalPolicyAuditEventResponse,
    ApprovalPolicyRouteRequest,
    ApprovalPolicyStageResponse,
    ApprovalPolicyStageWrite,
    ApprovalPolicyStatus,
    ApprovalPolicyVersionResponse,
    CreateApprovalPolicyRequest,
    CreateApprovalPolicyVersionRequest,
    DocumentDirection,
    Materiality,
)
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey, RoleKey
from agreement_intelligence_api.identity.service import IdentityService


class ApprovalPolicyService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def create(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: CreateApprovalPolicyRequest,
    ) -> ApprovalPolicyVersionResponse:
        self._authorize(principal, organization_id, workspace_id)
        policy = ApprovalPolicyRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=request.name,
            agreement_family=request.agreement_family,
            document_direction=request.document_direction,
            jurisdiction=_normalize_scope_value(request.jurisdiction),
            materiality=request.materiality,
            precedence=request.precedence,
            created_by=principal.user_id,
        )
        self._session.add(policy)
        self._session.flush()
        version = ApprovalPolicyVersionRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            policy_id=policy.id,
            version=1,
            status="draft",
            submitter_may_approve=request.submitter_may_approve,
            allow_cross_stage_same_approver=request.allow_cross_stage_same_approver,
            created_by=principal.user_id,
        )
        self._session.add(version)
        self._session.flush()
        self._add_stages(version, request.stages)
        self._audit(policy, version, principal.user_id, "draft_created")
        self._session.flush()
        response = self._response(version, policy)
        self._session.commit()
        return response

    def create_version(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        policy_id: UUID,
        request: CreateApprovalPolicyVersionRequest,
    ) -> ApprovalPolicyVersionResponse:
        self._authorize(principal, organization_id, workspace_id)
        policy = self._policy(policy_id, organization_id, workspace_id, lock_for_update=True)
        source = (
            self._version(policy_id, request.source_version, organization_id, workspace_id)
            if request.source_version is not None
            else None
        )
        next_version = (
            self._session.scalar(
                select(func.coalesce(func.max(ApprovalPolicyVersionRecord.version), 0) + 1).where(
                    ApprovalPolicyVersionRecord.policy_id == policy.id
                )
            )
            or 1
        )
        version = ApprovalPolicyVersionRecord(
            organization_id=organization_id,
            workspace_id=workspace_id,
            policy_id=policy.id,
            version=next_version,
            status="draft",
            submitter_may_approve=source.submitter_may_approve if source else False,
            allow_cross_stage_same_approver=(
                source.allow_cross_stage_same_approver if source else False
            ),
            created_by=principal.user_id,
        )
        self._session.add(version)
        self._session.flush()
        if source:
            for source_stage in source.stages:
                self._session.add(
                    ApprovalPolicyStageRecord(
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        policy_version_id=version.id,
                        ordinal=source_stage.ordinal,
                        name=source_stage.name,
                        approval_mode=source_stage.approval_mode,
                        quorum_count=source_stage.quorum_count,
                        eligible_role_keys=list(source_stage.eligible_role_keys),
                        eligible_user_ids=list(source_stage.eligible_user_ids),
                        deadline_hours=source_stage.deadline_hours,
                        escalation_role_key=source_stage.escalation_role_key,
                    )
                )
        self._audit(policy, version, principal.user_id, "draft_created")
        self._session.flush()
        response = self._response(version, policy)
        self._session.commit()
        return response

    def publish(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        policy_id: UUID,
        version_number: int,
    ) -> ApprovalPolicyVersionResponse:
        self._authorize(principal, organization_id, workspace_id)
        version = self._version(policy_id, version_number, organization_id, workspace_id)
        if version.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "published_approval_policy_immutable"},
            )
        self._validate_draft(version)
        existing = self._session.scalar(
            select(ApprovalPolicyVersionRecord.id)
            .where(ApprovalPolicyVersionRecord.policy_id == policy_id)
            .where(ApprovalPolicyVersionRecord.status == "published")
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "published_approval_policy_exists"},
            )
        self._ensure_no_equal_routing_match(version.policy, version.id)
        version.status = "published"
        version.published_at = datetime.now(UTC)
        self._audit(version.policy, version, principal.user_id, "published")
        self._session.flush()
        response = self._response(version, version.policy)
        self._session.commit()
        return response

    def list(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_family: str | None = None,
    ) -> list[ApprovalPolicyVersionResponse]:
        self._authorize(principal, organization_id, workspace_id)
        query = (
            select(ApprovalPolicyVersionRecord)
            .join(ApprovalPolicyVersionRecord.policy)
            .options(
                selectinload(ApprovalPolicyVersionRecord.policy),
                selectinload(ApprovalPolicyVersionRecord.stages),
            )
            .where(ApprovalPolicyVersionRecord.organization_id == organization_id)
            .where(ApprovalPolicyVersionRecord.workspace_id == workspace_id)
            .order_by(ApprovalPolicyRecord.name, ApprovalPolicyVersionRecord.version.desc())
        )
        if agreement_family:
            query = query.where(ApprovalPolicyRecord.agreement_family == agreement_family)
        return [self._response(version, version.policy) for version in self._session.scalars(query)]

    def route(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: ApprovalPolicyRouteRequest,
    ) -> ApprovalPolicyVersionResponse | None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_READ,
        ):
            hide_resource()
        candidates = list(
            self._session.scalars(
                select(ApprovalPolicyVersionRecord)
                .join(ApprovalPolicyVersionRecord.policy)
                .options(
                    selectinload(ApprovalPolicyVersionRecord.policy),
                    selectinload(ApprovalPolicyVersionRecord.stages),
                )
                .where(ApprovalPolicyVersionRecord.organization_id == organization_id)
                .where(ApprovalPolicyVersionRecord.workspace_id == workspace_id)
                .where(ApprovalPolicyVersionRecord.status == "published")
                .where(ApprovalPolicyRecord.agreement_family == request.agreement_family)
            )
        )
        matches = [
            candidate
            for candidate in candidates
            if _scope_matches(candidate.policy.document_direction, request.document_direction)
            and _scope_matches(candidate.policy.jurisdiction, request.jurisdiction)
            and _scope_matches(candidate.policy.materiality, request.materiality)
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: _route_sort_key(item.policy), reverse=True)
        selected = matches[0]
        if len(matches) > 1 and _route_sort_key(matches[1].policy) == _route_sort_key(
            selected.policy
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "approval_policy_routing_conflict"},
            )
        return self._response(selected, selected.policy)

    def _add_stages(
        self, version: ApprovalPolicyVersionRecord, stages: Sequence[ApprovalPolicyStageWrite]
    ) -> None:
        for ordinal, stage in enumerate(stages, start=1):
            self._session.add(
                ApprovalPolicyStageRecord(
                    organization_id=version.organization_id,
                    workspace_id=version.workspace_id,
                    policy_version_id=version.id,
                    ordinal=ordinal,
                    name=stage.name,
                    approval_mode=stage.approval_mode,
                    quorum_count=stage.quorum_count,
                    eligible_role_keys=stage.eligible_role_keys,
                    eligible_user_ids=[str(user_id) for user_id in stage.eligible_user_ids],
                    deadline_hours=stage.deadline_hours,
                    escalation_role_key=stage.escalation_role_key,
                )
            )

    def _validate_draft(self, version: ApprovalPolicyVersionRecord) -> None:
        stages = list(version.stages)
        if not stages:
            self._invalid_draft("approval policy requires at least one stage")
        for expected_ordinal, stage in enumerate(stages, start=1):
            if stage.ordinal != expected_ordinal:
                self._invalid_draft("approval policy stages must have consecutive ordering")
            eligible_roles = set(stage.eligible_role_keys)
            eligible_users = set(stage.eligible_user_ids)
            if not eligible_roles and not eligible_users:
                self._invalid_draft("approval policy stage requires an eligible role or user")
            invalid_roles = eligible_roles.difference({role.value for role in RoleKey})
            if invalid_roles:
                self._invalid_draft("approval policy stage contains an unsupported role")
            if stage.escalation_role_key and stage.escalation_role_key not in {
                role.value for role in RoleKey
            }:
                self._invalid_draft("approval policy stage contains an unsupported escalation role")
            eligible_count = len(eligible_roles) + len(eligible_users)
            if stage.approval_mode == "quorum":
                if stage.quorum_count is None or stage.quorum_count > eligible_count:
                    self._invalid_draft("approval policy stage quorum exceeds eligible approvers")
            elif stage.quorum_count is not None:
                self._invalid_draft("approval policy stage quorum is only valid for quorum mode")

    def _ensure_no_equal_routing_match(
        self, policy: ApprovalPolicyRecord, version_id: UUID
    ) -> None:
        candidates = self._session.scalars(
            select(ApprovalPolicyVersionRecord)
            .join(ApprovalPolicyVersionRecord.policy)
            .where(ApprovalPolicyVersionRecord.organization_id == policy.organization_id)
            .where(ApprovalPolicyVersionRecord.workspace_id == policy.workspace_id)
            .where(ApprovalPolicyVersionRecord.status == "published")
            .where(ApprovalPolicyVersionRecord.id != version_id)
            .where(ApprovalPolicyRecord.agreement_family == policy.agreement_family)
            .options(selectinload(ApprovalPolicyVersionRecord.policy))
        )
        has_conflict = any(
            _route_sort_key(candidate.policy) == _route_sort_key(policy)
            and _routing_scopes_overlap(candidate.policy, policy)
            for candidate in candidates
        )
        if has_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "approval_policy_routing_conflict"},
            )

    def _policy(
        self,
        policy_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        *,
        lock_for_update: bool = False,
    ) -> ApprovalPolicyRecord:
        query = (
            select(ApprovalPolicyRecord)
            .options(
                selectinload(ApprovalPolicyRecord.versions).selectinload(
                    ApprovalPolicyVersionRecord.stages
                )
            )
            .where(ApprovalPolicyRecord.id == policy_id)
            .where(ApprovalPolicyRecord.organization_id == organization_id)
            .where(ApprovalPolicyRecord.workspace_id == workspace_id)
        )
        if lock_for_update:
            query = query.with_for_update()
        policy = self._session.scalar(query)
        if policy is None:
            hide_resource()
        return policy

    def _version(
        self, policy_id: UUID, version_number: int, organization_id: UUID, workspace_id: UUID
    ) -> ApprovalPolicyVersionRecord:
        version = self._session.scalar(
            select(ApprovalPolicyVersionRecord)
            .options(
                selectinload(ApprovalPolicyVersionRecord.policy),
                selectinload(ApprovalPolicyVersionRecord.stages),
            )
            .where(ApprovalPolicyVersionRecord.policy_id == policy_id)
            .where(ApprovalPolicyVersionRecord.version == version_number)
            .where(ApprovalPolicyVersionRecord.organization_id == organization_id)
            .where(ApprovalPolicyVersionRecord.workspace_id == workspace_id)
        )
        if version is None:
            hide_resource()
        return version

    def _audit(
        self,
        policy: ApprovalPolicyRecord,
        version: ApprovalPolicyVersionRecord,
        actor_id: UUID,
        action: str,
    ) -> None:
        self._session.add(
            ApprovalPolicyAuditEventRecord(
                organization_id=policy.organization_id,
                workspace_id=policy.workspace_id,
                policy_id=policy.id,
                policy_version_id=version.id,
                actor_id=actor_id,
                action=action,
                metadata_json={},
            )
        )

    def _response(
        self, version: ApprovalPolicyVersionRecord, policy: ApprovalPolicyRecord
    ) -> ApprovalPolicyVersionResponse:
        events = list(
            self._session.scalars(
                select(ApprovalPolicyAuditEventRecord)
                .where(ApprovalPolicyAuditEventRecord.policy_version_id == version.id)
                .order_by(
                    ApprovalPolicyAuditEventRecord.occurred_at, ApprovalPolicyAuditEventRecord.id
                )
            )
        )
        return ApprovalPolicyVersionResponse(
            id=version.id,
            policy_id=policy.id,
            organization_id=policy.organization_id,
            workspace_id=policy.workspace_id,
            name=policy.name,
            version=version.version,
            status=cast(ApprovalPolicyStatus, version.status),
            agreement_family=policy.agreement_family,
            document_direction=cast(DocumentDirection, policy.document_direction),
            jurisdiction=policy.jurisdiction,
            materiality=cast(Materiality, policy.materiality),
            precedence=policy.precedence,
            submitter_may_approve=version.submitter_may_approve,
            allow_cross_stage_same_approver=version.allow_cross_stage_same_approver,
            stages=[
                ApprovalPolicyStageResponse(
                    id=stage.id,
                    ordinal=stage.ordinal,
                    name=stage.name,
                    approval_mode=cast(ApprovalMode, stage.approval_mode),
                    quorum_count=stage.quorum_count,
                    eligible_role_keys=list(stage.eligible_role_keys),
                    eligible_user_ids=[UUID(value) for value in stage.eligible_user_ids],
                    deadline_hours=stage.deadline_hours,
                    escalation_role_key=stage.escalation_role_key,
                )
                for stage in version.stages
            ],
            audit_events=[
                ApprovalPolicyAuditEventResponse(
                    action=event.action,
                    actor_id=event.actor_id,
                    occurred_at=event.occurred_at,
                    metadata=event.metadata_json,
                )
                for event in events
            ],
            created_at=version.created_at,
            published_at=version.published_at,
        )

    def _authorize(self, principal: Principal, organization_id: UUID, workspace_id: UUID) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.APPROVAL_POLICIES_MANAGE,
        ):
            hide_resource()

    def _invalid_draft(self, message: str) -> None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_approval_policy_draft", "message": message},
        )


def _scope_matches(policy_value: str, requested_value: str) -> bool:
    return policy_value == "any" or policy_value == requested_value


def _normalize_scope_value(value: str) -> str:
    return "any" if value.casefold() == "any" else value.upper()


def _route_sort_key(policy: ApprovalPolicyRecord) -> tuple[int, int]:
    specificity = sum(
        value != "any"
        for value in (policy.document_direction, policy.jurisdiction, policy.materiality)
    )
    return specificity, policy.precedence


def _routing_scopes_overlap(first: ApprovalPolicyRecord, second: ApprovalPolicyRecord) -> bool:
    return all(
        _scope_values_overlap(first_value, second_value)
        for first_value, second_value in zip(
            (first.document_direction, first.jurisdiction, first.materiality),
            (second.document_direction, second.jurisdiction, second.materiality),
            strict=True,
        )
    )


def _scope_values_overlap(first: str, second: str) -> bool:
    return first == "any" or second == "any" or first == second
