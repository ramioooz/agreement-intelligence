from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.retrieval.models import (
    RetrievalChunkEmbeddingRecord,
    RetrievalChunkRecord,
    RetrievalIndexBuildRecord,
)


@dataclass(frozen=True)
class RetrievalEmbeddingCandidate:
    """Authorized vector candidate with the source anchors needed for grounded retrieval."""

    agreement_id: UUID
    build_id: UUID
    chunk_id: str
    content: str
    anchor_ids: tuple[str, ...]
    embedding: list[float]
    index_version: str
    dimensions: int


class SQLAlchemyRetrievalChunkRepository:
    """Read-only retrieval contract for embedding and search stories."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def active_chunks(
        self, *, organization_id: UUID, workspace_id: UUID, agreement_id: UUID
    ) -> list[RetrievalChunkRecord]:
        return list(
            self._session.scalars(
                select(RetrievalChunkRecord)
                .join(RetrievalIndexBuildRecord)
                .where(
                    RetrievalChunkRecord.organization_id == organization_id,
                    RetrievalChunkRecord.workspace_id == workspace_id,
                    RetrievalChunkRecord.agreement_id == agreement_id,
                    RetrievalIndexBuildRecord.organization_id == organization_id,
                    RetrievalIndexBuildRecord.workspace_id == workspace_id,
                    RetrievalIndexBuildRecord.state == "active",
                )
                .order_by(RetrievalChunkRecord.ordinal)
            )
        )

    def active_embedding_candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        index_version: str,
        dimensions: int,
        agreement_ids: tuple[UUID, ...] | None = None,
    ) -> list[RetrievalEmbeddingCandidate]:
        """Return only active, ready embeddings in one exact version/dimension space."""

        statement = (
            select(RetrievalChunkRecord, RetrievalChunkEmbeddingRecord)
            .join(
                RetrievalIndexBuildRecord,
                RetrievalChunkRecord.build_id == RetrievalIndexBuildRecord.id,
            )
            .join(
                RetrievalChunkEmbeddingRecord,
                (RetrievalChunkEmbeddingRecord.agreement_id == RetrievalChunkRecord.agreement_id)
                & (RetrievalChunkEmbeddingRecord.build_id == RetrievalChunkRecord.build_id)
                & (RetrievalChunkEmbeddingRecord.chunk_id == RetrievalChunkRecord.chunk_id),
            )
            .where(
                RetrievalChunkRecord.organization_id == organization_id,
                RetrievalChunkRecord.workspace_id == workspace_id,
                RetrievalIndexBuildRecord.organization_id == organization_id,
                RetrievalIndexBuildRecord.workspace_id == workspace_id,
                RetrievalIndexBuildRecord.state == "active",
                RetrievalChunkEmbeddingRecord.organization_id == organization_id,
                RetrievalChunkEmbeddingRecord.workspace_id == workspace_id,
                RetrievalChunkEmbeddingRecord.index_version == index_version,
                RetrievalChunkEmbeddingRecord.dimensions == dimensions,
                RetrievalChunkEmbeddingRecord.state == "ready",
            )
            .order_by(RetrievalChunkRecord.agreement_id, RetrievalChunkRecord.ordinal)
        )
        if agreement_ids is not None:
            statement = statement.where(RetrievalChunkRecord.agreement_id.in_(agreement_ids))
        return [
            RetrievalEmbeddingCandidate(
                agreement_id=chunk.agreement_id,
                build_id=chunk.build_id,
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                anchor_ids=tuple(chunk.anchor_ids),
                embedding=embedding.embedding or [],
                index_version=embedding.index_version,
                dimensions=embedding.dimensions,
            )
            for chunk, embedding in self._session.execute(statement).all()
        ]
