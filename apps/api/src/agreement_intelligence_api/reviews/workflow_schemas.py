from uuid import UUID

from pydantic import BaseModel, Field


class StartReviewWorkflowRequest(BaseModel):
    policy_version_id: UUID


class ReviewWorkflowDecisionRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject|request_changes)$")
    idempotency_key: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(ge=0)


class ReviewWorkflowStageResponse(BaseModel):
    ordinal: int
    state: str


class ReviewWorkflowResponse(BaseModel):
    id: UUID
    state: str
    active_stage_ordinal: int | None
    checkpoint_id: UUID
    revision: int
    stages: list[ReviewWorkflowStageResponse]


class FinalReviewPackageResponse(BaseModel):
    pdf_url: str
    manifest_url: str
    checksum: str
    created_at: str
    manifest_checksum: str | None = None
    pdf_checksum: str | None = None
