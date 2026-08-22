from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, NoReturn, cast
from uuid import UUID, uuid4

from agreement_intelligence_worker.fallback_suggestions import (
    FallbackSuggestion,
    FallbackSuggestionRequest,
    bounded_comparison_kind,
    render_comparison,
    suggest_fallback,
)
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.documents.storage import DocumentStorage
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.playbooks.models import PlaybookRuleRecord, PlaybookVersionRecord
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from agreement_intelligence_api.reviews.decisions import decision_history_response
from agreement_intelligence_api.reviews.models import (
    PlaybookEvaluationRecord,
    PlaybookFindingRecord,
)
from agreement_intelligence_api.reviews.schemas import (
    FallbackSuggestionResponse,
    FindingResult,
    PlaybookEvaluationResponse,
    PlaybookFindingResponse,
    RiskPayloadResponse,
    SubmitPlaybookEvaluationRequest,
)

_MINIMUM_CONFIDENCE = 0.8


class PlaybookEvaluationService:
    def __init__(
        self, session: Session, identity: IdentityService, storage: DocumentStorage
    ) -> None:
        self._session = session
        self._identity = identity
        self._storage = storage

    def submit(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        request: SubmitPlaybookEvaluationRequest,
    ) -> PlaybookEvaluationResponse:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        agreement = self._agreement(agreement_id, organization_id, workspace_id)
        version = self._version(request.playbook_version_id, organization_id, workspace_id)
        if version.status != "published":
            self._invalid("published_playbook_required")
        if version.playbook.agreement_family != agreement.agreement_type:
            self._invalid("playbook_family_mismatch")
        artifact = self._completed_artifact(agreement_id, organization_id, workspace_id)
        if artifact is None:
            self._invalid("completed_analysis_required", conflict=True)
        processing_job_id, artifact_key = artifact
        existing = self._session.scalar(
            select(PlaybookEvaluationRecord)
            .options(
                selectinload(PlaybookEvaluationRecord.findings).selectinload(
                    PlaybookFindingRecord.decisions
                )
            )
            .where(PlaybookEvaluationRecord.organization_id == organization_id)
            .where(PlaybookEvaluationRecord.workspace_id == workspace_id)
            .where(PlaybookEvaluationRecord.agreement_id == agreement_id)
            .where(PlaybookEvaluationRecord.processing_job_id == processing_job_id)
            .where(PlaybookEvaluationRecord.playbook_version_id == version.id)
        )
        if existing is not None:
            return self._response(
                existing,
                version.id,
                {rule.id: rule for rule in version.rules},
            )
        stored = self._storage.read(artifact_key)
        if stored is None:
            self._invalid("completed_analysis_required", conflict=True)
        analysis = _analysis_document(stored.content)
        if analysis is None:
            self._invalid("completed_analysis_required", conflict=True)

        analysis_version = _string(analysis.get("schema_version"), "unknown")
        findings = [_evaluate(rule, analysis) for rule in version.rules]
        extraction_version = next(
            (finding[5] for finding in findings if finding[5] != "unknown"), "unknown"
        )
        evaluation = PlaybookEvaluationRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            processing_job_id=processing_job_id,
            playbook_version_id=version.id,
            analysis_version=analysis_version,
            extraction_version=extraction_version,
            state="completed",
            requested_by=principal.user_id,
            created_at=datetime.now(UTC),
        )
        self._session.add(evaluation)
        self._session.flush()
        for rule, result, confidence, citations, method, clause_extraction_version in findings:
            self._session.add(
                PlaybookFindingRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    evaluation_id=evaluation.id,
                    rule_id=rule.id,
                    result=result.value,
                    severity=rule.severity,
                    confidence=confidence,
                    method=method,
                    citation_ids=citations,
                    extraction_version=clause_extraction_version,
                    review_state="unreviewed",
                    risk_payload=_risk_payload(rule, result, confidence, citations),
                    fallback_suggestions=_fallback_suggestion_payloads(
                        rule, result, citations, version.id
                    ),
                )
            )
        self._session.flush()
        response = self._response(
            evaluation,
            version.id,
            {rule.id: rule for rule in version.rules},
        )
        self._session.commit()
        return response

    def list(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
    ) -> list[PlaybookEvaluationResponse]:
        self._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
        self._agreement(agreement_id, organization_id, workspace_id)
        records = list(
            self._session.scalars(
                select(PlaybookEvaluationRecord)
                .options(
                    selectinload(PlaybookEvaluationRecord.findings).selectinload(
                        PlaybookFindingRecord.decisions
                    )
                )
                .where(PlaybookEvaluationRecord.organization_id == organization_id)
                .where(PlaybookEvaluationRecord.workspace_id == workspace_id)
                .where(PlaybookEvaluationRecord.agreement_id == agreement_id)
                .order_by(desc(PlaybookEvaluationRecord.created_at), PlaybookEvaluationRecord.id)
            )
        )
        version_ids = {record.playbook_version_id for record in records}
        rules_by_version: dict[UUID, dict[UUID, PlaybookRuleRecord]] = {}
        if version_ids:
            for rule in self._session.scalars(
                select(PlaybookRuleRecord)
                .where(PlaybookRuleRecord.organization_id == organization_id)
                .where(PlaybookRuleRecord.workspace_id == workspace_id)
                .where(PlaybookRuleRecord.playbook_version_id.in_(version_ids))
            ):
                rules_by_version.setdefault(rule.playbook_version_id, {})[rule.id] = rule
        return [
            self._response(
                record,
                record.playbook_version_id,
                rules_by_version.get(record.playbook_version_id, {}),
            )
            for record in records
        ]

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

    def _agreement(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> AgreementRecord:
        record = self._session.scalar(
            select(AgreementRecord)
            .where(AgreementRecord.id == agreement_id)
            .where(AgreementRecord.organization_id == organization_id)
            .where(AgreementRecord.workspace_id == workspace_id)
        )
        if record is None:
            hide_resource()
        return record

    def _version(
        self, version_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> PlaybookVersionRecord:
        record = self._session.scalar(
            select(PlaybookVersionRecord)
            .options(
                selectinload(PlaybookVersionRecord.playbook),
                selectinload(PlaybookVersionRecord.rules),
            )
            .where(PlaybookVersionRecord.id == version_id)
            .where(PlaybookVersionRecord.organization_id == organization_id)
            .where(PlaybookVersionRecord.workspace_id == workspace_id)
        )
        if record is None:
            hide_resource()
        return record

    def _completed_artifact(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> tuple[UUID, str] | None:
        row = self._session.execute(
            select(ProcessingJobRecord.id, ProcessingArtifactRecord.artifact_key)
            .join(ProcessingJobRecord, ProcessingArtifactRecord.job_id == ProcessingJobRecord.id)
            .where(ProcessingArtifactRecord.agreement_id == agreement_id)
            .where(ProcessingJobRecord.organization_id == organization_id)
            .where(ProcessingJobRecord.workspace_id == workspace_id)
            .where(ProcessingJobRecord.state == "completed")
            .order_by(desc(ProcessingArtifactRecord.created_at))
            .limit(1)
        ).first()
        return (row[0], row[1]) if row is not None else None

    @staticmethod
    def _response(
        record: PlaybookEvaluationRecord,
        playbook_version_id: UUID,
        rules_by_id: Mapping[UUID, PlaybookRuleRecord],
    ) -> PlaybookEvaluationResponse:
        return PlaybookEvaluationResponse(
            id=record.id,
            agreement_id=record.agreement_id,
            processing_job_id=record.processing_job_id,
            playbook_version_id=playbook_version_id,
            analysis_version=record.analysis_version,
            extraction_version=record.extraction_version,
            state=record.state,
            findings=[
                PlaybookFindingResponse(
                    id=finding.id,
                    rule_id=finding.rule_id,
                    rule_title=(
                        rules_by_id[finding.rule_id].title
                        if finding.rule_id in rules_by_id
                        else str(finding.rule_id)
                    ),
                    clause_type=(
                        rules_by_id[finding.rule_id].clause_type
                        if finding.rule_id in rules_by_id
                        else "unknown"
                    ),
                    reviewer_guidance=(
                        rules_by_id[finding.rule_id].reviewer_guidance
                        if finding.rule_id in rules_by_id
                        else ""
                    ),
                    result=FindingResult(finding.result),
                    severity=finding.severity,
                    confidence=finding.confidence,
                    method=cast(Literal["deterministic", "semantic"], finding.method),
                    citation_ids=finding.citation_ids,
                    playbook_version_id=playbook_version_id,
                    extraction_version=finding.extraction_version,
                    review_state=finding.review_state,
                    risk=_risk_response(finding),
                    fallback_suggestions=_fallback_suggestion_responses(
                        finding,
                        playbook_version_id,
                        rules_by_id.get(finding.rule_id),
                    ),
                    decision_events=decision_history_response(finding).events,
                    current_decision=decision_history_response(finding).current,
                )
                for finding in record.findings
            ],
            created_at=_required_aware(record.created_at),
        )

    @staticmethod
    def _invalid(code: str, *, conflict: bool = False) -> NoReturn:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT if conflict else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail={"code": code},
        )


def _evaluate(
    rule: PlaybookRuleRecord, analysis: Mapping[str, object]
) -> tuple[PlaybookRuleRecord, FindingResult, float, list[str], str, str]:
    clauses = analysis.get("clauses", [])
    candidates = (
        [
            item
            for item in clauses
            if isinstance(item, Mapping)
            and _normalized(item.get("category")) == _normalized(rule.clause_type)
            and _is_deterministic_clause(item)
        ]
        if isinstance(clauses, list)
        else []
    )
    if not candidates:
        return rule, FindingResult.NEEDS_REVIEW, 0.0, [], "deterministic", "unknown"
    clause = max(candidates, key=_clause_authority)
    confidence = _confidence(clause)
    citations = _citations(clause)
    extraction_version = _string(clause.get("extraction_version"), "unknown")
    if confidence < _MINIMUM_CONFIDENCE or not citations:
        return (
            rule,
            FindingResult.NEEDS_REVIEW,
            confidence,
            citations,
            "deterministic",
            extraction_version,
        )
    source_text = _string(clause.get("source_text"), "").casefold()
    expected = (rule.preferred_language or "").strip().casefold()
    if not expected:
        return (
            rule,
            FindingResult.NEEDS_REVIEW,
            confidence,
            citations,
            "deterministic",
            extraction_version,
        )
    matches = bool(expected) and expected in source_text
    if rule.policy_type == "prohibited":
        result = FindingResult.NON_COMPLIANT if matches else FindingResult.SATISFIED
    else:
        result = FindingResult.SATISFIED if matches else FindingResult.NEEDS_REVIEW
    return rule, result, confidence, citations, "deterministic", extraction_version


def _risk_payload(
    rule: PlaybookRuleRecord,
    result: FindingResult,
    confidence: float,
    citation_ids: list[str],
) -> dict[str, object]:
    rationale = (
        rule.legal_rationale.strip() or "The deterministic finding requires reviewer assessment."
    )
    return {
        "version": "playbook-risk.v1",
        "severity": rule.severity,
        "risk_rationale": rationale,
        "risk_confidence": min(1.0, max(0.0, confidence)),
        "review_status": (
            "review_required"
            if result
            in {FindingResult.MISSING, FindingResult.NON_COMPLIANT, FindingResult.NEEDS_REVIEW}
            else "complete"
        ),
        "citation_ids": citation_ids,
        "model_explanation": None,
    }


def _fallback_suggestion_payloads(
    rule: PlaybookRuleRecord,
    result: FindingResult,
    citation_ids: list[str],
    playbook_version_id: UUID,
) -> list[dict[str, object]]:
    suggestion = suggest_fallback(
        FallbackSuggestionRequest(
            rule_id=str(rule.id),
            playbook_version_id=str(playbook_version_id),
            finding_result=result.value,
            citation_ids=citation_ids,
            cited_clause_text=None,
            preferred_language=rule.preferred_language,
            fallback_language=rule.fallback_language,
        )
    )
    return [_fallback_suggestion_payload(suggestion)] if suggestion is not None else []


def _fallback_suggestion_payload(suggestion: FallbackSuggestion) -> dict[str, object]:
    return {
        "version": suggestion.version,
        "rule_id": suggestion.rule_id,
        "playbook_version_id": suggestion.playbook_version_id,
        "suggested_language": suggestion.suggested_language,
        "review_recommendation": suggestion.review_recommendation,
        "citation_ids": suggestion.citation_ids,
        "comparison_kind": suggestion.comparison_kind,
        "comparison": suggestion.comparison,
        "ai_generated": suggestion.ai_generated,
    }


def _risk_response(finding: PlaybookFindingRecord) -> RiskPayloadResponse:
    fallback = _fallback_risk_payload(finding)
    try:
        risk = RiskPayloadResponse.model_validate(finding.risk_payload)
    except ValidationError:
        return fallback
    if (
        risk.severity != fallback.severity
        or risk.risk_confidence != fallback.risk_confidence
        or risk.review_status != fallback.review_status
        or risk.citation_ids != fallback.citation_ids
    ):
        return fallback
    return risk


def _fallback_risk_payload(finding: PlaybookFindingRecord) -> RiskPayloadResponse:
    return RiskPayloadResponse(
        version="playbook-risk.v1",
        severity=finding.severity,
        risk_rationale="The deterministic finding requires reviewer assessment.",
        risk_confidence=min(1.0, max(0.0, finding.confidence)),
        review_status=(
            "review_required"
            if finding.result in {"missing", "non_compliant", "needs_review"}
            else "complete"
        ),
        citation_ids=finding.citation_ids,
        model_explanation=None,
    )


def _fallback_suggestion_responses(
    finding: PlaybookFindingRecord,
    playbook_version_id: UUID,
    rule: PlaybookRuleRecord | None,
) -> list[FallbackSuggestionResponse]:
    stored: object = finding.fallback_suggestions
    if rule is None or not isinstance(stored, list) or len(stored) != 1:
        return []
    try:
        result = FindingResult(finding.result)
    except ValueError:
        return []
    expected = suggest_fallback(
        FallbackSuggestionRequest(
            rule_id=str(rule.id),
            playbook_version_id=str(playbook_version_id),
            finding_result=result.value,
            citation_ids=finding.citation_ids,
            cited_clause_text=None,
            preferred_language=rule.preferred_language,
            fallback_language=rule.fallback_language,
        )
    )
    if expected is None:
        return []
    try:
        suggestion = FallbackSuggestionResponse.model_validate(stored[0])
    except ValidationError:
        return []
    if (
        suggestion.rule_id != finding.rule_id
        or suggestion.playbook_version_id != playbook_version_id
        or suggestion.suggested_language != expected.suggested_language
        or suggestion.review_recommendation != expected.review_recommendation
        or suggestion.citation_ids != expected.citation_ids
        or suggestion.ai_generated != (suggestion.comparison_kind is not None)
        or suggestion.comparison != render_comparison(suggestion.comparison_kind)
    ):
        return []
    request = FallbackSuggestionRequest(
        rule_id=str(rule.id),
        playbook_version_id=str(playbook_version_id),
        finding_result=result.value,
        citation_ids=finding.citation_ids,
        cited_clause_text=None,
        preferred_language=rule.preferred_language,
        fallback_language=rule.fallback_language,
    )
    if (
        suggestion.comparison_kind is not None
        and bounded_comparison_kind(request, suggestion.comparison_kind, suggestion.citation_ids)
        is None
    ):
        return []
    return [suggestion]


def _analysis_document(content: bytes) -> Mapping[str, object] | None:
    import json

    try:
        value: object = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _string(value, "").casefold()).strip("_")


def _confidence(clause: Mapping[str, object]) -> float:
    value = clause.get("confidence")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _clause_authority(clause: Mapping[str, object]) -> tuple[bool, float]:
    return _is_deterministic_clause(clause), _confidence(clause)


def _is_deterministic_clause(clause: Mapping[str, object]) -> bool:
    version = clause.get("extraction_version")
    return isinstance(version, str) and version.startswith("clause-rules.")


def _citations(clause: Mapping[str, object]) -> list[str]:
    value = clause.get("citation_anchor_ids")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _required_aware(value: datetime | None) -> datetime:
    if value is None:
        raise RuntimeError("persisted evaluation timestamp is missing")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
