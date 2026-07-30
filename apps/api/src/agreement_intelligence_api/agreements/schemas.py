from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AgreementStatus = Literal["draft", "active", "expired", "terminated"]
ProcessingState = Literal["pending", "processing", "completed", "failed"]


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=100)


class AgreementFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1, max_length=500)
    content_type: str = Field(min_length=1, max_length=100)
    storage_key: str = Field(min_length=1, max_length=1024)
    checksum: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0)
    version_number: int = Field(ge=1)


class AuditEvent(BaseModel):
    action: Literal["created", "archived", "restored"]
    actor_id: str
    occurred_at: datetime


class CreateAgreementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    agreement_type: str = Field(min_length=1, max_length=100)
    status: AgreementStatus = "draft"
    parties: list[Party] = Field(default_factory=list)
    files: list[AgreementFile] = Field(default_factory=list)
    processing_state: ProcessingState = "pending"
    audit_metadata: dict[str, str] = Field(default_factory=dict)


class AgreementResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    title: str
    agreement_type: str
    status: AgreementStatus
    parties: list[Party]
    files: list[AgreementFile]
    processing_state: ProcessingState
    audit_metadata: dict[str, str]
    audit_events: list[AuditEvent]
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgreementPage(BaseModel):
    limit: int
    next_cursor: str | None


class AgreementListResponse(BaseModel):
    items: list[AgreementResponse]
    page: AgreementPage


class ErrorResponse(BaseModel):
    code: str
    message: str
    correlation_id: str
