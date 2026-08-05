from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    actor_id: UUID
    action: str
    resource_type: str
    resource_id: UUID | None
    outcome: str
    correlation_id: str
    before_ref: dict[str, Any]
    after_ref: dict[str, Any]
    metadata: dict[str, Any]
    occurred_at: datetime
