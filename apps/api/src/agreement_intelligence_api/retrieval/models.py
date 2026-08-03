from datetime import datetime
from uuid import UUID, uuid4

from agreement_intelligence_worker.vector_types import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
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
        ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            [
                "agreements.id",
                "agreements.organization_id",
                "agreements.workspace_id",
            ],
            name="fk_retrieval_index_builds_agreement_scope",
        ),
        UniqueConstraint(
            "agreement_id",
            "source_checksum",
            "chunker_version",
            name="uq_retrieval_index_build_source",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            "workspace_id",
            "agreement_id",
            name="uq_retrieval_index_build_scope",
        ),
        Index(
            "ix_retrieval_index_builds_scope_active",
            "organization_id",
            "workspace_id",
            "agreement_id",
            "state",
        ),
        Index(
            "uq_retrieval_index_builds_active_scope",
            "organization_id",
            "workspace_id",
            "agreement_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
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
        ForeignKeyConstraint(
            ["build_id", "organization_id", "workspace_id", "agreement_id"],
            [
                "retrieval_index_builds.id",
                "retrieval_index_builds.organization_id",
                "retrieval_index_builds.workspace_id",
                "retrieval_index_builds.agreement_id",
            ],
            name="fk_retrieval_chunks_build_scope",
        ),
        PrimaryKeyConstraint("agreement_id", "build_id", "chunk_id", name="pk_retrieval_chunks"),
        Index(
            "ix_retrieval_chunks_scope_build",
            "organization_id",
            "workspace_id",
            "agreement_id",
            "build_id",
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(80))
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


class RetrievalChunkEmbeddingRecord(Base):
    __tablename__ = "retrieval_chunk_embeddings"
    __table_args__ = (
        PrimaryKeyConstraint(
            "agreement_id",
            "build_id",
            "chunk_id",
            "index_version",
            "dimensions",
            name="pk_retrieval_chunk_embeddings",
        ),
        Index(
            "ix_retrieval_chunk_embeddings_scope_ready",
            "organization_id",
            "workspace_id",
            "agreement_id",
            "index_version",
            "dimensions",
            "state",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    agreement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    build_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    chunk_id: Mapped[str] = mapped_column(String(80))
    index_version: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(256))
    configuration_version: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    retry_outcome: Mapped[str] = mapped_column(String(64))
    fallback_outcome: Mapped[str] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
