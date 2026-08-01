from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PlaybookStatus = Literal["draft", "published"]
PolicyType = Literal["required", "prohibited", "preferred"]
Severity = Literal["low", "medium", "high", "critical"]
EvaluationMethod = Literal["deterministic", "semantic"]


class RuleEvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: EvaluationMethod = "deterministic"
    semantic_assessment_permitted: bool = False


class PlaybookRuleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_type: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=256)
    policy_type: PolicyType = "required"
    preferred_language: str | None = None
    fallback_language: str | None = None
    severity: Severity = "medium"
    legal_rationale: str = ""
    reviewer_guidance: str = ""
    evaluation_config: RuleEvaluationConfig = Field(default_factory=RuleEvaluationConfig)


class UpdatePlaybookRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_type: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=256)
    policy_type: PolicyType | None = None
    preferred_language: str | None = None
    fallback_language: str | None = None
    severity: Severity | None = None
    legal_rationale: str | None = None
    reviewer_guidance: str | None = None
    evaluation_config: RuleEvaluationConfig | None = None


class CreatePlaybookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    agreement_family: str = Field(min_length=1, max_length=100)
    rules: list[PlaybookRuleWrite] = Field(default_factory=list)


class CreatePlaybookVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version: int | None = Field(default=None, ge=1)


class PlaybookRuleResponse(BaseModel):
    id: UUID
    clause_type: str
    title: str
    policy_type: PolicyType
    preferred_language: str | None
    fallback_language: str | None
    severity: Severity
    legal_rationale: str
    reviewer_guidance: str
    evaluation_config: RuleEvaluationConfig


class PlaybookAuditEventResponse(BaseModel):
    action: str
    actor_id: str
    occurred_at: datetime
    metadata: dict[str, Any]


class PlaybookVersionResponse(BaseModel):
    id: UUID
    playbook_id: UUID
    organization_id: UUID
    workspace_id: UUID
    name: str
    version: int
    status: PlaybookStatus
    agreement_family: str
    rules: list[PlaybookRuleResponse]
    audit_events: list[PlaybookAuditEventResponse]
    created_at: datetime
    published_at: datetime | None
