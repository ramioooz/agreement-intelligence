from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from agreement_intelligence_api.identity.models import Base


class RetrievalIndexBuildRecord(Base):
    __tablename__ = "retrieval_index_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        UniqueConstraint(
            "agreement_id",
            "source_checksum",
            "chunker_version",
            name="uq_retrieval_index_build_source",
        ),
        Index(
            "ix_retrieval_index_builds_scope_active",
            "organization_id",
            "workspace_id",
            "agreement_id",
            "state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    source_checksum: Mapped[str] = mapped_column(String(255))
    chunker_version: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RetrievalChunkRecord(Base):
    __tablename__ = "retrieval_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        Index(
            "ix_retrieval_chunks_scope_build",
            "organization_id",
            "workspace_id",
            "agreement_id",
            "build_id",
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(ForeignKey("agreements.id"), index=True)
    build_id: Mapped[UUID] = mapped_column(ForeignKey("retrieval_index_builds.id"), index=True)
    source_checksum: Mapped[str] = mapped_column(String(255))
    chunker_version: Mapped[str] = mapped_column(String(100))
    ordinal: Mapped[int] = mapped_column(Integer)
    heading_path: Mapped[list[str]] = mapped_column(JSON)
    anchor_ids: Mapped[list[str]] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(String)
