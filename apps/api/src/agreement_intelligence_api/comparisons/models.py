from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class VersionComparisonRunRecord(Base):
    __tablename__ = "version_comparison_runs"
    __table_args__ = (
        UniqueConstraint(
            "agreement_id",
            "baseline_version_id",
            "target_version_id",
            "analysis_version",
            name="uq_version_comparison_identity",
        ),
        UniqueConstraint(
            "agreement_id", "idempotency_key", name="uq_version_comparison_idempotency"
        ),
        Index("ix_version_comparison_scope_state", "organization_id", "workspace_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    baseline_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agreement_versions.id"), index=True
    )
    target_version_id: Mapped[UUID] = mapped_column(ForeignKey("agreement_versions.id"), index=True)
    processing_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_jobs.id"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255))
    analysis_version: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(32), index=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    analysis_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VersionComparisonChangeRecord(Base):
    __tablename__ = "version_comparison_changes"
    __table_args__ = (
        UniqueConstraint(
            "comparison_run_id", "ordinal", name="uq_version_comparison_change_ordinal"
        ),
        Index("ix_version_comparison_changes_run", "comparison_run_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    comparison_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("version_comparison_runs.id"), index=True
    )
    organization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    alignment_kind: Mapped[str] = mapped_column(String(32))
    baseline_element_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_element_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    baseline_citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    word_diff: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float]
    review_required: Mapped[bool]
    severity: Mapped[str] = mapped_column(String(16))
    legal_concepts: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(String(2000))
    provider_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
