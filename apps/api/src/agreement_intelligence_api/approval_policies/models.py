from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agreement_intelligence_api.identity.models import Base


class ApprovalPolicyRecord(Base):
    __tablename__ = "approval_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_approval_policies_scope_id"
        ),
        Index(
            "ix_approval_policies_scope_family",
            "organization_id",
            "workspace_id",
            "agreement_family",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(256))
    agreement_family: Mapped[str] = mapped_column(String(100), index=True)
    document_direction: Mapped[str] = mapped_column(String(32), default="any")
    jurisdiction: Mapped[str] = mapped_column(String(16), default="any")
    materiality: Mapped[str] = mapped_column(String(16), default="any")
    precedence: Mapped[int] = mapped_column(Integer, default=100)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    versions: Mapped[list["ApprovalPolicyVersionRecord"]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="ApprovalPolicyVersionRecord.version",
    )


class ApprovalPolicyVersionRecord(Base):
    __tablename__ = "approval_policy_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "policy_id"],
            [
                "approval_policies.organization_id",
                "approval_policies.workspace_id",
                "approval_policies.id",
            ],
            name="fk_approval_policy_versions_scope_policy",
        ),
        UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_approval_policy_versions_scope_id"
        ),
        UniqueConstraint("policy_id", "version", name="uq_approval_policy_versions_policy_version"),
        Index(
            "ix_approval_policy_versions_scope_status", "organization_id", "workspace_id", "status"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    submitter_may_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_cross_stage_same_approver: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy: Mapped[ApprovalPolicyRecord] = relationship(back_populates="versions")
    stages: Mapped[list["ApprovalPolicyStageRecord"]] = relationship(
        back_populates="policy_version",
        cascade="all, delete-orphan",
        order_by="ApprovalPolicyStageRecord.ordinal",
    )


class ApprovalPolicyStageRecord(Base):
    __tablename__ = "approval_policy_stages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "policy_version_id"],
            [
                "approval_policy_versions.organization_id",
                "approval_policy_versions.workspace_id",
                "approval_policy_versions.id",
            ],
            name="fk_approval_policy_stages_scope_version",
        ),
        UniqueConstraint("policy_version_id", "ordinal", name="uq_approval_policy_stages_ordinal"),
        Index(
            "ix_approval_policy_stages_scope_version",
            "organization_id",
            "workspace_id",
            "policy_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    policy_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(256))
    approval_mode: Mapped[str] = mapped_column(String(16))
    quorum_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eligible_role_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    eligible_user_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    deadline_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalation_role_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[ApprovalPolicyVersionRecord] = relationship(back_populates="stages")


class ApprovalPolicyAuditEventRecord(Base):
    __tablename__ = "approval_policy_audit_events"
    __table_args__ = (
        Index(
            "ix_approval_policy_audit_events_scope_version",
            "organization_id",
            "workspace_id",
            "policy_version_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    policy_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def _reject_policy_audit_mutation(*_: object) -> None:
    raise ValueError("approval policy audit events are immutable")


event.listen(ApprovalPolicyAuditEventRecord, "before_update", _reject_policy_audit_mutation)
event.listen(ApprovalPolicyAuditEventRecord, "before_delete", _reject_policy_audit_mutation)
