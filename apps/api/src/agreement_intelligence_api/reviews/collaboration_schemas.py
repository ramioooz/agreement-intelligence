from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class StartReviewRequest(BaseModel):
    agreement_id: UUID
    agreement_version_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    policy_version_id: UUID | None = None
    policy_override_reason: str | None = Field(default=None, min_length=1, max_length=1000)


class ReviewCaseResponse(BaseModel):
    id: UUID
    agreement_id: UUID
    agreement_version_id: UUID | None
    state: str
    created_by: UUID
    revision: int
    created_at: datetime


class CreateAssignmentRequest(BaseModel):
    assignee_id: UUID
    due_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)


class ReassignAssignmentRequest(CreateAssignmentRequest):
    expected_revision: int = Field(ge=0)


class ReviewAssignmentResponse(BaseModel):
    id: UUID
    review_id: UUID
    assignee_id: UUID
    assigned_by: UUID
    predecessor_assignment_id: UUID | None
    due_at: datetime | None
    status: str
    created_at: datetime


class CreateReviewCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    finding_id: UUID | None = None
    agreement_version_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("body")
    @classmethod
    def body_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment body must not be blank")
        return value.strip()


class ReviewCommentResponse(BaseModel):
    id: UUID
    review_id: UUID
    finding_id: UUID | None
    agreement_version_id: UUID | None
    author_id: UUID
    body: str
    created_at: datetime


class ReviewNotificationSummaryResponse(BaseModel):
    unread_count: int
