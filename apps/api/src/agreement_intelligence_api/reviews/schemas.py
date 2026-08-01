from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FindingResult(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"


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
