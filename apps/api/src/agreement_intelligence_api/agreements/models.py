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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class AgreementRecord(Base):
    __tablename__ = "agreements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            "workspace_id",
            name="uq_agreements_scope",
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
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    comparison_baseline_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AgreementVersionRecord(Base):
    __tablename__ = "agreement_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            ["agreements.id", "agreements.organization_id", "agreements.workspace_id"],
        ),
        UniqueConstraint("agreement_id", "version_number", name="uq_agreement_version_number"),
        UniqueConstraint("agreement_id", "checksum", name="uq_agreement_version_checksum"),
        UniqueConstraint(
            "agreement_id", "idempotency_key", name="uq_agreement_version_idempotency"
        ),
        Index(
            "ix_agreement_versions_scope_lineage",
            "organization_id",
            "workspace_id",
            "agreement_id",
            "version_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version_number: Mapped[int]
    predecessor_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agreement_versions.id"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int]
    uploaded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processing_state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    processing_job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analysis_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255))


class AgreementVersionAuditEventRecord(Base):
    __tablename__ = "agreement_version_audit_events"
    __table_args__ = (
        Index(
            "ix_agreement_version_audit_scope_version",
            "organization_id",
            "workspace_id",
            "version_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgreementDeletionAuditEventRecord(Base):
    __tablename__ = "agreement_deletion_audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(500))
    agreement_type: Mapped[str] = mapped_column(String(100))
    file_checksums: Mapped[list[str]] = mapped_column(JSON, default=list)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
