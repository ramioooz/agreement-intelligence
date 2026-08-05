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


class ReviewCaseRecord(Base):
    """A tenant-scoped human review case for one immutable agreement version."""

    __tablename__ = "review_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "agreement_id",
            "agreement_version_id",
            "idempotency_key",
            name="uq_review_cases_idempotency",
        ),
        Index("ix_review_cases_scope_created", "organization_id", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    agreement_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agreement_versions.id"), index=True, nullable=True
    )
    state: Mapped[str] = mapped_column(String(32), default="open", index=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assignments: Mapped[list["ReviewAssignmentRecord"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )
    comments: Mapped[list["ReviewCommentRecord"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class ReviewAssignmentRecord(Base):
    __tablename__ = "review_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint("review_id", "idempotency_key", name="uq_review_assignments_idempotency"),
        Index(
            "ix_review_assignments_inbox",
            "organization_id",
            "workspace_id",
            "assignee_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("review_cases.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    assignee_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    assigned_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    predecessor_assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("review_assignments.id"), nullable=True, index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    review: Mapped[ReviewCaseRecord] = relationship(back_populates="assignments")


class ReviewCommentRecord(Base):
    __tablename__ = "review_comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint("review_id", "idempotency_key", name="uq_review_comments_idempotency"),
        Index("ix_review_comments_scope_review", "organization_id", "workspace_id", "review_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("review_cases.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    finding_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    agreement_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    body: Mapped[str] = mapped_column(String(4000))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    review: Mapped[ReviewCaseRecord] = relationship(back_populates="comments")


class ReviewNotificationEventRecord(Base):
    """Durable, provider-neutral notification outbox consumed by a later dispatcher."""

    __tablename__ = "review_notification_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_review_notification_events_idempotency"),
        Index("ix_review_notification_events_pending", "delivered_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("review_cases.id"), index=True)
    recipient_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewWorkflowRecord(Base):
    """Authoritative workflow state for a review; graph checkpoints are a recovery aid."""

    __tablename__ = "review_workflows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint("review_id", name="uq_review_workflows_review"),
        UniqueConstraint("checkpoint_id", name="uq_review_workflows_checkpoint"),
        Index("ix_review_workflows_scope_state", "organization_id", "workspace_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("review_cases.id"), index=True)
    policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("approval_policy_versions.id"), index=True
    )
    checkpoint_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), default=uuid4)
    state: Mapped[str] = mapped_column(String(32), default="waiting_for_approval", index=True)
    active_stage_ordinal: Mapped[int | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stages: Mapped[list["ReviewWorkflowStageRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ReviewWorkflowStageRecord.ordinal",
    )
    decisions: Mapped[list["ReviewWorkflowDecisionRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ReviewWorkflowDecisionRecord.occurred_at",
    )
    outbox_events: Mapped[list["ReviewWorkflowOutboxRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ReviewWorkflowOutboxRecord.created_at",
    )


class ReviewWorkflowStageRecord(Base):
    __tablename__ = "review_workflow_stages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint("workflow_id", "ordinal", name="uq_review_workflow_stages_ordinal"),
        Index("ix_review_workflow_stages_active", "workflow_id", "state", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("review_workflows.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    policy_stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("approval_policy_stages.id"), index=True
    )
    ordinal: Mapped[int] = mapped_column()
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workflow: Mapped[ReviewWorkflowRecord] = relationship(back_populates="stages")


class ReviewWorkflowDecisionRecord(Base):
    __tablename__ = "review_workflow_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "workflow_id", "idempotency_key", name="uq_review_workflow_decisions_idempotency"
        ),
        Index("ix_review_workflow_decisions_stage", "workflow_stage_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("review_workflows.id"), index=True)
    workflow_stage_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_workflow_stages.id"), index=True
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    workflow: Mapped[ReviewWorkflowRecord] = relationship(back_populates="decisions")


class ReviewWorkflowOutboxRecord(Base):
    """Transactional wake-up events. Delivery is at-least-once and consumers are idempotent."""

    __tablename__ = "review_workflow_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_review_workflow_outbox_idempotency"),
        Index("ix_review_workflow_outbox_pending", "delivered_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("review_workflows.id"), index=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    workflow: Mapped[ReviewWorkflowRecord] = relationship(back_populates="outbox_events")


def _reject_workflow_decision_mutation(*_: object) -> None:
    raise ValueError("review workflow decisions are immutable")


event.listen(ReviewWorkflowDecisionRecord, "before_update", _reject_workflow_decision_mutation)
event.listen(ReviewWorkflowDecisionRecord, "before_delete", _reject_workflow_decision_mutation)


class ReviewFinalPackageRecord(Base):
    """Immutable, stored artifacts generated once for a terminal review."""

    __tablename__ = "review_final_packages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint("review_id", name="uq_review_final_packages_review"),
        Index(
            "ix_review_final_packages_scope_review",
            "organization_id",
            "workspace_id",
            "review_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    review_id: Mapped[UUID] = mapped_column(ForeignKey("review_cases.id"), index=True)
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("review_workflows.id"), index=True)
    state: Mapped[str] = mapped_column(String(32))
    manifest_key: Mapped[str] = mapped_column(String(512), unique=True)
    pdf_key: Mapped[str] = mapped_column(String(512), unique=True)
    manifest_checksum: Mapped[str] = mapped_column(String(128))
    pdf_checksum: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _reject_final_package_mutation(*_: object) -> None:
    raise ValueError("review final packages are immutable")


event.listen(ReviewFinalPackageRecord, "before_update", _reject_final_package_mutation)
event.listen(ReviewFinalPackageRecord, "before_delete", _reject_final_package_mutation)
