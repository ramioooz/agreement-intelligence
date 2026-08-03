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
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class QuestionThreadRecord(Base):
    __tablename__ = "question_threads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint("id", "organization_id", "workspace_id", name="uq_question_threads_scope"),
        Index("ix_question_threads_scope_created", "organization_id", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionTurnRecord(Base):
    __tablename__ = "question_turns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "organization_id", "workspace_id"],
            [
                "question_threads.id",
                "question_threads.organization_id",
                "question_threads.workspace_id",
            ],
            name="fk_question_turns_thread_scope",
        ),
        Index(
            "ix_question_turns_scope_thread_created",
            "organization_id",
            "workspace_id",
            "thread_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    thread_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    question: Mapped[str] = mapped_column(String(1000))
    answer_status: Mapped[str] = mapped_column(String(32))
    answer_message: Mapped[str] = mapped_column(String)
    claims: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    retrieval_provenance: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuestionAuditEventRecord(Base):
    """Append-only audit record for persistent Q&A activity.

    The event intentionally contains identifiers and outcome only. Questions,
    answer text, retrieved evidence, and provider content remain in their
    purpose-specific records and never enter the audit trail.
    """

    __tablename__ = "question_audit_events"
    __table_args__ = (
        Index(
            "ix_question_audit_events_scope_thread_occurred",
            "organization_id",
            "workspace_id",
            "thread_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    thread_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    turn_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def _reject_audit_mutation(*_: object) -> None:
    raise ValueError("Question audit events are immutable")


event.listen(QuestionAuditEventRecord, "before_update", _reject_audit_mutation)
event.listen(QuestionAuditEventRecord, "before_delete", _reject_audit_mutation)
