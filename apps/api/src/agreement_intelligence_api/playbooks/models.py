from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agreement_intelligence_api.identity.models import Base


class LegalPlaybookRecord(Base):
    __tablename__ = "legal_playbooks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_legal_playbooks_scope_family", "organization_id", "workspace_id", "agreement_family"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(256))
    agreement_family: Mapped[str] = mapped_column(String(100), index=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    versions: Mapped[list["PlaybookVersionRecord"]] = relationship(
        back_populates="playbook", cascade="all, delete-orphan"
    )


class PlaybookVersionRecord(Base):
    __tablename__ = "playbook_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index("ix_playbook_versions_scope_status", "organization_id", "workspace_id", "status"),
        Index("uq_playbook_versions_playbook_version", "playbook_id", "version", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    playbook_id: Mapped[UUID] = mapped_column(ForeignKey("legal_playbooks.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    playbook: Mapped[LegalPlaybookRecord] = relationship(back_populates="versions")
    rules: Mapped[list["PlaybookRuleRecord"]] = relationship(
        back_populates="playbook_version", cascade="all, delete-orphan"
    )


class PlaybookRuleRecord(Base):
    __tablename__ = "playbook_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_playbook_rules_scope_version",
            "organization_id",
            "workspace_id",
            "playbook_version_id",
        ),
        Index(
            "uq_playbook_rules_version_clause_type",
            "playbook_version_id",
            "clause_type",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    playbook_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbook_versions.id"), index=True
    )
    clause_type: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(256), default="")
    policy_type: Mapped[str] = mapped_column(String(16), default="required")
    preferred_language: Mapped[str | None] = mapped_column(String, nullable=True)
    fallback_language: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    legal_rationale: Mapped[str] = mapped_column(String, default="")
    reviewer_guidance: Mapped[str] = mapped_column(String, default="")
    evaluation_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    playbook_version: Mapped[PlaybookVersionRecord] = relationship(back_populates="rules")


class PlaybookAuditEventRecord(Base):
    __tablename__ = "playbook_audit_events"
    __table_args__ = (
        Index(
            "ix_playbook_audit_events_scope_version",
            "organization_id",
            "workspace_id",
            "playbook_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    playbook_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    playbook_version_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    playbook_rule_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
