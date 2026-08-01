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


class PlaybookFindingResponse(BaseModel):
    id: UUID
    rule_id: UUID
    result: FindingResult
    severity: str
    confidence: float
    method: Literal["deterministic", "semantic"]
    citation_ids: list[str]
    playbook_version_id: UUID
    extraction_version: str
    review_state: str


class PlaybookEvaluationResponse(BaseModel):
    id: UUID
    agreement_id: UUID
    playbook_version_id: UUID
    analysis_version: str
    extraction_version: str
    state: str
    findings: list[PlaybookFindingResponse]
    created_at: datetime
