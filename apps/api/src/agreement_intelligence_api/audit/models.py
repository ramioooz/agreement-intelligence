from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class AuditEventRecord(Base):
    """A safe, immutable record of a business-relevant action.

    References describe the state transition using identifiers and state names;
    raw agreement data remains in purpose-specific storage and is never copied
    into the general ledger.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_audit_events_scope_occurred",
            "organization_id",
            "workspace_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_scope_resource_occurred",
            "organization_id",
            "workspace_id",
            "resource_type",
            "resource_id",
            "occurred_at",
        ),
        Index("ix_audit_events_correlation_id", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    correlation_id: Mapped[str] = mapped_column(String(64))
    before_ref: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_ref: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def _reject_audit_mutation(*_: object) -> None:
    raise ValueError("audit events are immutable")


event.listen(AuditEventRecord, "before_update", _reject_audit_mutation)
event.listen(AuditEventRecord, "before_delete", _reject_audit_mutation)
