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
    event,
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
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "id",
            name="uq_playbook_findings_scope_id",
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
    risk_payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    fallback_suggestions: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    evaluation: Mapped[PlaybookEvaluationRecord] = relationship(back_populates="findings")
    decisions: Mapped[list["ReviewDecisionRecord"]] = relationship(
        back_populates="finding",
        order_by="ReviewDecisionRecord.occurred_at, ReviewDecisionRecord.id",
    )


class ReviewDecisionRecord(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "finding_id"],
            [
                "playbook_findings.organization_id",
                "playbook_findings.workspace_id",
                "playbook_findings.id",
            ],
            name="fk_review_decisions_finding_scope",
        ),
        Index(
            "ix_review_decisions_scope_finding",
            "organization_id",
            "workspace_id",
            "finding_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(16))
    original_result: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(String)
    edited_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    edited_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finding: Mapped[PlaybookFindingRecord] = relationship(back_populates="decisions")


class ReviewAuditEventRecord(Base):
    __tablename__ = "review_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_review_audit_events_scope_occurred",
            "organization_id",
            "workspace_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    finding_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    agreement_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def _reject_decision_mutation(*_: object) -> None:
    raise ValueError("review decision events are immutable")


event.listen(ReviewDecisionRecord, "before_update", _reject_decision_mutation)
event.listen(ReviewDecisionRecord, "before_delete", _reject_decision_mutation)
