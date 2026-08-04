from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProcessingJobState = Literal["queued", "processing", "completed", "failed"]


class SubmitProcessingJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = Field(default="baseline", min_length=1, max_length=100)


class ProcessingJobResponse(BaseModel):
    id: UUID
    agreement_id: UUID
    version_id: UUID | None = None
    state: ProcessingJobState
    attempt_count: int
    failure_category: str | None
    failure_message: str | None
    next_retry_at: datetime | None
    queued_at: datetime
    processing_started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    retry_permitted: bool
