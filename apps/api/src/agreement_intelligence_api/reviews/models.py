from datetime import datetime
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agreement_intelligence_api.identity.models import Base


class PlaybookEvaluationRecord(Base):
    __tablename__ = "playbook_evaluations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_playbook_evaluations_scope_agreement",
            "organization_id",
            "workspace_id",
            "agreement_id",
        ),
        UniqueConstraint(
            "processing_job_id", "playbook_version_id", name="uq_playbook_evaluations_job_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    processing_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_jobs.id"), index=True, nullable=True
    )
    playbook_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbook_versions.id"), index=True
    )
    analysis_version: Mapped[str] = mapped_column(String(100))
    extraction_version: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(32), default="completed")
    requested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    findings: Mapped[list["PlaybookFindingRecord"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class PlaybookFindingRecord(Base):
    __tablename__ = "playbook_findings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_playbook_findings_scope_evaluation",
            "organization_id",
            "workspace_id",
            "evaluation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("playbook_evaluations.id"), index=True)
    rule_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    result: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float]
    method: Mapped[str] = mapped_column(String(16))
    citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_version: Mapped[str] = mapped_column(String(100))
    review_state: Mapped[str] = mapped_column(String(32), default="unreviewed")
    evaluation: Mapped[PlaybookEvaluationRecord] = relationship(back_populates="findings")
