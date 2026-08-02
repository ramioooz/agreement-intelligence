from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator


class FindingResult(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"


class ReviewDecisionAction(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewDecisionAction
    rationale: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
    ]
    edited_result: FindingResult | None = None
    edited_severity: Literal["critical", "high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def validate_edited_values(self) -> "ReviewDecisionRequest":
        has_edits = self.edited_result is not None or self.edited_severity is not None
        if self.action is ReviewDecisionAction.EDITED and not has_edits:
            raise ValueError("edited decisions require an edited result or severity")
        if self.action is not ReviewDecisionAction.EDITED and has_edits:
            raise ValueError("only edited decisions may include edited values")
        return self


class ReviewDecisionEventResponse(BaseModel):
    id: UUID
    finding_id: UUID
    action: ReviewDecisionAction
    original_result: FindingResult
    rationale: str
    edited_result: FindingResult | None
    edited_severity: str | None
    actor_id: UUID
    occurred_at: datetime


class CurrentReviewDecisionResponse(BaseModel):
    action: ReviewDecisionAction
    result: FindingResult
    severity: str
    rationale: str
    actor_id: UUID
    decided_at: datetime


class ReviewDecisionResponse(ReviewDecisionEventResponse):
    current: CurrentReviewDecisionResponse


class ReviewDecisionHistoryResponse(BaseModel):
    finding_id: UUID
    events: list[ReviewDecisionEventResponse]
    current: CurrentReviewDecisionResponse | None


class SubmitPlaybookEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook_version_id: UUID


class RiskPayloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["playbook-risk.v1"]
    severity: str
    risk_rationale: str
    risk_confidence: float
    review_status: str
    citation_ids: list[str]
    model_explanation: str | None


class FallbackSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["playbook-fallback-suggestion.v1"]
    rule_id: UUID
    playbook_version_id: UUID
    suggested_language: str | None
    review_recommendation: str
    citation_ids: list[str]
    comparison_kind: Literal["clause_differs_from_approved_position"] | None = None
    comparison: str | None
    ai_generated: bool


class PlaybookFindingResponse(BaseModel):
    id: UUID
    rule_id: UUID
    rule_title: str
    clause_type: str
    reviewer_guidance: str
    result: FindingResult
    severity: str
    confidence: float
    method: Literal["deterministic", "semantic"]
    citation_ids: list[str]
    playbook_version_id: UUID
    extraction_version: str
    review_state: str
    risk: RiskPayloadResponse
    fallback_suggestions: list[FallbackSuggestionResponse]
    decision_events: list[ReviewDecisionEventResponse]
    current_decision: CurrentReviewDecisionResponse | None


class PlaybookEvaluationResponse(BaseModel):
    id: UUID
    agreement_id: UUID
    processing_job_id: UUID | None
    playbook_version_id: UUID
    analysis_version: str
    extraction_version: str
    state: str
    findings: list[PlaybookFindingResponse]
    created_at: datetime
