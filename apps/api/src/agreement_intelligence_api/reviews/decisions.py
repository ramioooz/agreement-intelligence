from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.audit.service import AuditEventWriter
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.models import (
    PlaybookEvaluationRecord,
    PlaybookFindingRecord,
    ReviewAuditEventRecord,
    ReviewDecisionRecord,
)
from agreement_intelligence_api.reviews.schemas import (
    CurrentReviewDecisionResponse,
    FindingResult,
    ReviewDecisionAction,
    ReviewDecisionEventResponse,
    ReviewDecisionHistoryResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)


class ReviewDecisionService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def record(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        finding_id: UUID,
        request: ReviewDecisionRequest,
    ) -> ReviewDecisionResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        finding = self._finding(finding_id, organization_id, workspace_id, lock_agreement=True)
        now = datetime.now(UTC)
        decision = ReviewDecisionRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            finding_id=finding.id,
            action=request.action.value,
            original_result=finding.result,
            rationale=request.rationale.strip(),
            edited_result=request.edited_result.value if request.edited_result else None,
            edited_severity=request.edited_severity,
            actor_id=principal.user_id,
            occurred_at=now,
        )
        self._session.add(decision)
        self._session.add(
            ReviewAuditEventRecord(
                id=uuid4(),
                organization_id=organization_id,
                workspace_id=workspace_id,
                action="decision_recorded",
                actor_id=principal.user_id,
                finding_id=finding.id,
                agreement_id=None,
                metadata_json={"decision_id": str(decision.id), "action": request.action.value},
                occurred_at=now,
            )
        )
        AuditEventWriter(self._session).record(
            organization_id=organization_id,
            workspace_id=workspace_id,
            actor_id=principal.user_id,
            action="review_finding_decision_recorded",
            resource_type="review_finding",
            resource_id=finding.id,
            outcome="succeeded",
            before_ref={"review_state": finding.review_state},
            after_ref={"decision_id": str(decision.id), "review_state": "decided"},
            metadata={
                "finding_id": str(finding.id),
                "decision_action": request.action.value,
            },
            occurred_at=now,
        )
        self._session.flush()
        events = [*finding.decisions, decision]
        current = _current_decision(finding, events)
        if current is None:
            raise RuntimeError("a recorded decision must produce current state")
        response = ReviewDecisionResponse(
            **_event_response(decision).model_dump(),
            current=current,
        )
        self._session.commit()
        return response

    def history(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        finding_id: UUID,
    ) -> ReviewDecisionHistoryResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        finding = self._finding(finding_id, organization_id, workspace_id)
        return decision_history_response(finding)

    def _authorize(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.REVIEWS_DECIDE,
        ):
            hide_resource()

    def _finding(
        self,
        finding_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        *,
        lock_agreement: bool = False,
    ) -> PlaybookFindingRecord:
        statement = (
            select(PlaybookFindingRecord)
            .join(
                PlaybookEvaluationRecord,
                PlaybookFindingRecord.evaluation_id == PlaybookEvaluationRecord.id,
            )
            .join(AgreementRecord, PlaybookEvaluationRecord.agreement_id == AgreementRecord.id)
            .options(selectinload(PlaybookFindingRecord.decisions))
            .where(PlaybookFindingRecord.id == finding_id)
            .where(PlaybookFindingRecord.organization_id == organization_id)
            .where(PlaybookFindingRecord.workspace_id == workspace_id)
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )
        if lock_agreement:
            statement = statement.with_for_update(of=AgreementRecord)
        finding = self._session.scalar(statement)
        if finding is None:
            hide_resource()
        return finding


def decision_history_response(finding: PlaybookFindingRecord) -> ReviewDecisionHistoryResponse:
    events = sorted(finding.decisions, key=_decision_order)
    return ReviewDecisionHistoryResponse(
        finding_id=finding.id,
        events=[_event_response(event) for event in events],
        current=_current_decision(finding, events),
    )


def _current_decision(
    finding: PlaybookFindingRecord,
    events: list[ReviewDecisionRecord],
) -> CurrentReviewDecisionResponse | None:
    if not events:
        return None
    result = FindingResult(finding.result)
    severity = finding.severity
    latest = events[-1]
    for event in events:
        if event.action == ReviewDecisionAction.EDITED.value:
            if event.edited_result is not None:
                result = FindingResult(event.edited_result)
            if event.edited_severity is not None:
                severity = event.edited_severity
        else:
            result = FindingResult(finding.result)
            severity = finding.severity
    return CurrentReviewDecisionResponse(
        action=ReviewDecisionAction(latest.action),
        result=result,
        severity=severity,
        rationale=latest.rationale,
        actor_id=latest.actor_id,
        decided_at=_aware(latest.occurred_at),
    )


def _event_response(event: ReviewDecisionRecord) -> ReviewDecisionEventResponse:
    return ReviewDecisionEventResponse(
        id=event.id,
        finding_id=event.finding_id,
        action=ReviewDecisionAction(event.action),
        original_result=FindingResult(event.original_result),
        rationale=event.rationale,
        edited_result=FindingResult(event.edited_result) if event.edited_result else None,
        edited_severity=event.edited_severity,
        actor_id=event.actor_id,
        occurred_at=_aware(event.occurred_at),
    )


def _decision_order(event: ReviewDecisionRecord) -> tuple[datetime, UUID]:
    return _aware(event.occurred_at), event.id


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
