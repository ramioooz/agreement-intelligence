from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIOperation(StrEnum):
    DOCUMENT_ANALYSIS = "document_analysis"
    EMBEDDING = "embedding"
    GROUNDED_QA = "grounded_qa"
    VERSION_MATERIALITY = "version_materiality"


class CreateAIConfigurationRequest(BaseModel):
    operation: AIOperation
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=64)
    prompt_template: str = Field(min_length=1)
    schema_definition: dict[str, Any] = Field(alias="schema")
    model_route: str = Field(min_length=1, max_length=256)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_definition")
    @classmethod
    def schema_must_be_an_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("schema must not be empty")
        return value


class PromoteAIConfigurationRequest(BaseModel):
    environment: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")


class AIConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    operation: AIOperation
    version: str
    prompt_template: str
    prompt_checksum: str
    schema_definition: dict[str, Any] = Field(alias="schema", serialization_alias="schema")
    schema_checksum: str
    model_route: str
    parameters: dict[str, Any]
    status: str
    created_by: UUID
    created_at: datetime | None
    published_at: datetime | None


class AIConfigurationPromotionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    configuration_id: UUID
    operation: AIOperation
    environment: str
    promoted_by: UUID
    promoted_at: datetime | None
