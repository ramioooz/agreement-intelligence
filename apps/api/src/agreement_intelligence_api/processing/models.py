from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class ProcessingJobRecord(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "(claim_token IS NULL) = (claim_lease_expires_at IS NULL)",
            name="ck_processing_jobs_claim_lease_pair",
        ),
        UniqueConstraint("agreement_id", "idempotency_key", name="uq_processing_job_idempotency"),
        Index("ix_processing_jobs_agreement_state", "agreement_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agreement_versions.id"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255))
    profile: Mapped[str] = mapped_column(String(100))
    source_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    claim_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingArtifactRecord(Base):
    __tablename__ = "processing_artifacts"
    __table_args__ = (
        UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_job_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    artifact_key: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingArtifactIntentRecord(Base):
    """Durable expected key written before a processor may mutate object storage."""

    __tablename__ = "processing_artifact_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            ["agreements.id", "agreements.organization_id", "agreements.workspace_id"],
            name="fk_processing_artifact_intents_agreement_scope",
        ),
        CheckConstraint(
            "category IN ('analysis', 'comparison')",
            name="ck_processing_artifact_intents_category",
        ),
        CheckConstraint(
            "state IN ('expected', 'settled')",
            name="ck_processing_artifact_intents_state",
        ),
        UniqueConstraint("job_id", name="uq_processing_artifact_intents_job"),
        UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_intent_job_key"),
        Index(
            "ix_processing_artifact_intents_scope_agreement",
            "organization_id",
            "workspace_id",
            "agreement_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    profile: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(32))
    artifact_key: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(32), default="expected", server_default="expected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingOutboxRecord(Base):
    __tablename__ = "processing_outbox"
    __table_args__ = (Index("ix_processing_outbox_pending", "delivered_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    profile: Mapped[str] = mapped_column(String(100))
    attempt_count: Mapped[int]
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
