from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
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


class DocumentObjectRegistryRecord(Base):
    __tablename__ = "document_object_registry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "object_key", name="uq_document_object_registry_key"
        ),
        CheckConstraint(
            "state IN ('available', 'deleting', 'deleted')",
            name="ck_document_object_registry_state",
        ),
        Index(
            "ix_document_object_registry_scope_state",
            "organization_id",
            "workspace_id",
            "state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    object_key: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    __table_args__ = (
        UniqueConstraint(
            "deletion_id",
            "event_type",
            "retry_cycle",
            name="uq_agreement_deletion_audit_terminal_cycle",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(500))
    agreement_type: Mapped[str] = mapped_column(String(100))
    file_checksums: Mapped[list[str]] = mapped_column(JSON, default=list)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    deletion_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), default="requested")
    retry_cycle: Mapped[int] = mapped_column(default=1)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgreementDeletionRequestRecord(Base):
    __tablename__ = "agreement_deletion_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            ["agreements.id", "agreements.organization_id", "agreements.workspace_id"],
            name="fk_agreement_deletion_requests_agreement_scope",
        ),
        UniqueConstraint("agreement_id", name="uq_agreement_deletion_requests_agreement"),
        UniqueConstraint(
            "id",
            "organization_id",
            "workspace_id",
            "agreement_id",
            name="uq_agreement_deletion_requests_scope",
        ),
        Index(
            "ix_agreement_deletion_requests_scope_state",
            "organization_id",
            "workspace_id",
            "state",
        ),
        CheckConstraint(
            "state IN ('accepted', 'processing', 'retrying', 'completed', 'failed')",
            name="ck_agreement_deletion_requests_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_agreement_deletion_requests_attempts"),
        CheckConstraint("retry_cycle >= 1", name="ck_agreement_deletion_requests_retry_cycle"),
        CheckConstraint(
            "(claim_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_agreement_deletion_requests_lease_pair",
        ),
        CheckConstraint(
            "(state = 'processing') = (claim_token IS NOT NULL)",
            name="ck_agreement_deletion_requests_processing_lease",
        ),
        CheckConstraint(
            "(state = 'completed') = (completed_at IS NOT NULL)",
            name="ck_agreement_deletion_requests_completed_at",
        ),
        CheckConstraint(
            "(state = 'failed') = (failed_at IS NOT NULL)",
            name="ck_agreement_deletion_requests_failed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(500))
    agreement_type: Mapped[str] = mapped_column(String(100))
    file_checksums: Mapped[list[str]] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(32), default="accepted", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    retry_cycle: Mapped[int] = mapped_column(default=1)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgreementDeletionObjectRecord(Base):
    __tablename__ = "agreement_deletion_objects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["deletion_id", "organization_id", "workspace_id", "agreement_id"],
            [
                "agreement_deletion_requests.id",
                "agreement_deletion_requests.organization_id",
                "agreement_deletion_requests.workspace_id",
                "agreement_deletion_requests.agreement_id",
            ],
            name="fk_agreement_deletion_objects_request_scope",
        ),
        UniqueConstraint(
            "deletion_id", "category", "object_key", name="uq_agreement_deletion_objects_key"
        ),
        Index(
            "ix_agreement_deletion_objects_scope_state",
            "organization_id",
            "workspace_id",
            "state",
        ),
        CheckConstraint(
            "category IN ('source', 'analysis', 'comparison', 'review_manifest', 'review_pdf')",
            name="ck_agreement_deletion_objects_category",
        ),
        CheckConstraint(
            "state IN ('pending', 'deleted', 'preserved')",
            name="ck_agreement_deletion_objects_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    deletion_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    category: Mapped[str] = mapped_column(String(32))
    object_key: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(32), default="pending")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgreementDeletionOutboxRecord(Base):
    __tablename__ = "agreement_deletion_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["deletion_id", "organization_id", "workspace_id", "agreement_id"],
            [
                "agreement_deletion_requests.id",
                "agreement_deletion_requests.organization_id",
                "agreement_deletion_requests.workspace_id",
                "agreement_deletion_requests.agreement_id",
            ],
            name="fk_agreement_deletion_outbox_request_scope",
        ),
        UniqueConstraint("deletion_id", name="uq_agreement_deletion_outbox_deletion"),
        Index("ix_agreement_deletion_outbox_pending", "delivered_at", "next_attempt_at"),
        CheckConstraint("attempt_count >= 0", name="ck_agreement_deletion_outbox_attempts"),
        CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)",
            name="ck_agreement_deletion_outbox_lease_pair",
        ),
        CheckConstraint(
            "delivered_at IS NULL OR lease_token IS NULL",
            name="ck_agreement_deletion_outbox_delivered_unleased",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    deletion_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deletion: Mapped[AgreementDeletionRequestRecord] = relationship()
