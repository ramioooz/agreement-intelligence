from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ComparisonState = Literal["queued", "processing", "completed", "failed"]


class CreateVersionComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_version_id: UUID | None = None
    target_version_id: UUID | None = None
    analysis_version: str = Field(default="version-comparison.v1", min_length=1, max_length=100)


class VersionComparisonChangeResponse(BaseModel):
    id: UUID
    ordinal: int
    alignment_kind: str
    baseline_element_ids: list[str]
    target_element_ids: list[str]
    baseline_citation_ids: list[str]
    target_citation_ids: list[str]
    word_diff: list[dict[str, str]]
    confidence: float
    review_required: bool
    severity: str
    legal_concepts: list[str]
    rationale: str
    provider_provenance: dict[str, object]


class VersionComparisonRunResponse(BaseModel):
    id: UUID
    agreement_id: UUID
    baseline_version_id: UUID
    target_version_id: UUID
    processing_job_id: UUID | None
    analysis_version: str
    state: ComparisonState
    failure_category: str | None
    failure_message: str | None
    analysis_provenance: dict[str, object]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class VersionComparisonResultResponse(VersionComparisonRunResponse):
    changes: list[VersionComparisonChangeResponse]
