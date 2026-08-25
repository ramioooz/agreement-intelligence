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


class AIConfigurationVersionRecord(Base):
    __tablename__ = "ai_configuration_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "id",
            name="uq_ai_configuration_scope_id",
        ),
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "operation",
            "version",
            name="uq_ai_configuration_scope_operation_version",
        ),
        Index("ix_ai_configuration_operation_status", "operation", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_template: Mapped[str] = mapped_column(String, nullable=False)
    prompt_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    model_route: Mapped[str] = mapped_column(String(256), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIConfigurationPromotionRecord(Base):
    __tablename__ = "ai_configuration_promotions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "configuration_id"],
            [
                "ai_configuration_versions.organization_id",
                "ai_configuration_versions.workspace_id",
                "ai_configuration_versions.id",
            ],
        ),
        Index(
            "ix_ai_configuration_promotions_lookup",
            "organization_id",
            "workspace_id",
            "operation",
            "environment",
            "promoted_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    configuration_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    promoted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    promoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIConfigurationAuditEventRecord(Base):
    __tablename__ = "ai_configuration_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "workspace_id", "configuration_id"],
            [
                "ai_configuration_versions.organization_id",
                "ai_configuration_versions.workspace_id",
                "ai_configuration_versions.id",
            ],
        ),
        Index("ix_ai_configuration_audit_configuration", "configuration_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    configuration_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
