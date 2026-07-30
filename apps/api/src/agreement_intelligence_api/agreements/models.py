from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class AgreementRecord(Base):
    __tablename__ = "agreements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index("ix_agreements_scope_created", "organization_id", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(500))
    agreement_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    parties: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    processing_state: Mapped[str] = mapped_column(String(32))
    audit_metadata: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    audit_events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
