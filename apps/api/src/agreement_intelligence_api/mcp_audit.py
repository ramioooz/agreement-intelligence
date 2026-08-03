from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Index, String, Uuid, event, func
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class McpAuditEventRecord(Base):
    """Append-only audit record for a remote MCP tool invocation."""

    __tablename__ = "mcp_audit_events"
    __table_args__ = (
        Index(
            "ix_mcp_audit_events_scope_occurred",
            "organization_id",
            "workspace_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def _reject_audit_mutation(*_: object) -> None:
    raise ValueError("MCP audit events are immutable")


event.listen(McpAuditEventRecord, "before_update", _reject_audit_mutation)
event.listen(McpAuditEventRecord, "before_delete", _reject_audit_mutation)
