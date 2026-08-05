from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DocumentDirection = Literal["any", "first_party", "counterparty"]
Materiality = Literal["any", "low", "medium", "high", "critical"]
ApprovalMode = Literal["any", "all", "quorum"]
ApprovalPolicyStatus = Literal["draft", "published"]
SupportedAgreementFamily = Literal["client_agreement", "liquidity_provider_agreement"]


class ApprovalPolicyStageWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    approval_mode: ApprovalMode = "all"
    quorum_count: int | None = Field(default=None, ge=1)
    eligible_role_keys: list[str] = Field(default_factory=list)
    eligible_user_ids: list[UUID] = Field(default_factory=list)
    deadline_hours: int | None = Field(default=None, ge=1, le=8760)
    escalation_role_key: str | None = Field(default=None, min_length=1, max_length=64)


class CreateApprovalPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    agreement_family: SupportedAgreementFamily
    document_direction: DocumentDirection = "any"
    jurisdiction: str = Field(default="any", min_length=2, max_length=16)
    materiality: Materiality = "any"
    precedence: int = Field(default=100, ge=0, le=1000)
    submitter_may_approve: bool = False
    allow_cross_stage_same_approver: bool = False
    stages: list[ApprovalPolicyStageWrite] = Field(default_factory=list)


class CreateApprovalPolicyVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version: int | None = Field(default=None, ge=1)


class ApprovalPolicyStageResponse(BaseModel):
    id: UUID
    ordinal: int
    name: str
    approval_mode: ApprovalMode
    quorum_count: int | None
    eligible_role_keys: list[str]
    eligible_user_ids: list[UUID]
    deadline_hours: int | None
    escalation_role_key: str | None


class ApprovalPolicyAuditEventResponse(BaseModel):
    action: str
    actor_id: UUID
    occurred_at: datetime
    metadata: dict[str, Any]


class ApprovalPolicyVersionResponse(BaseModel):
    id: UUID
    policy_id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    version: int
    status: ApprovalPolicyStatus
    agreement_family: str
    document_direction: DocumentDirection
    jurisdiction: str
    materiality: Materiality
    precedence: int
    submitter_may_approve: bool
    allow_cross_stage_same_approver: bool
    stages: list[ApprovalPolicyStageResponse]
    audit_events: list[ApprovalPolicyAuditEventResponse]
    created_at: datetime
    published_at: datetime | None


class ApprovalPolicyRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreement_family: SupportedAgreementFamily
    document_direction: DocumentDirection = "any"
    jurisdiction: str = Field(default="any", min_length=2, max_length=16)
    materiality: Materiality = "any"

    @model_validator(mode="after")
    def normalize(self) -> "ApprovalPolicyRouteRequest":
        self.jurisdiction = (
            "any" if self.jurisdiction.casefold() == "any" else self.jurisdiction.upper()
        )
        return self
