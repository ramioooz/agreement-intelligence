from __future__ import annotations

from datetime import datetime
from math import sqrt
from uuid import UUID

from sqlalchemy import String, and_, cast, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.retrieval.models import (
    RetrievalChunkEmbeddingRecord,
    RetrievalChunkRecord,
    RetrievalIndexBuildRecord,
)
from agreement_intelligence_api.search.schemas import SearchFilters
from agreement_intelligence_api.search.service import EmbeddingSpace, RankedChunk


class SQLAlchemySearchRepository:
    """Read active, tenant-scoped retrieval chunks through PostgreSQL FTS."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def lexical_candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int,
    ) -> list[RankedChunk]:
        statement = (
            select(RetrievalChunkRecord, RetrievalIndexBuildRecord, AgreementRecord)
            .join(
                RetrievalIndexBuildRecord,
                and_(
                    RetrievalChunkRecord.build_id == RetrievalIndexBuildRecord.id,
                    RetrievalChunkRecord.organization_id
                    == RetrievalIndexBuildRecord.organization_id,
                    RetrievalChunkRecord.workspace_id == RetrievalIndexBuildRecord.workspace_id,
                    RetrievalChunkRecord.agreement_id == RetrievalIndexBuildRecord.agreement_id,
                ),
            )
            .join(AgreementRecord, RetrievalChunkRecord.agreement_id == AgreementRecord.id)
            .where(RetrievalChunkRecord.organization_id == organization_id)
            .where(RetrievalChunkRecord.workspace_id == workspace_id)
            .where(RetrievalIndexBuildRecord.state == "active")
            .where(AgreementRecord.archived_at.is_(None))
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )
        statement = _apply_filters(statement, filters)
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            ts_query = func.websearch_to_tsquery("english", filters.query)
            rank = func.ts_rank_cd(
                func.to_tsvector("english", RetrievalChunkRecord.content), ts_query
            )
            statement = statement.where(
                func.to_tsvector("english", RetrievalChunkRecord.content).op("@@")(ts_query)
            ).order_by(rank.desc(), RetrievalChunkRecord.chunk_id)
        else:
            statement = statement.where(
                func.lower(RetrievalChunkRecord.content).contains(filters.query.lower())
            ).order_by(RetrievalChunkRecord.chunk_id)
        rows = self._session.execute(statement.limit(limit)).all()
        return [
            RankedChunk(
                chunk_id=chunk.chunk_id,
                agreement_id=agreement.id,
                agreement_title=agreement.title,
                agreement_type=agreement.agreement_type,
                agreement_status=agreement.status,
                source_checksum=chunk.source_checksum,
                chunker_version=chunk.chunker_version,
                build_id=build.id,
                anchor_ids=tuple(chunk.anchor_ids),
                content=chunk.content,
            )
            for chunk, build, agreement in rows
        ]

    def semantic_candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        query_embedding: list[float],
        index_version: str,
        dimensions: int,
        configuration_version: str,
        model: str,
        limit: int,
    ) -> list[RankedChunk]:
        """Read ready vectors from the exact active embedding index space.

        PostgreSQL ranks with pgvector cosine distance. The portable path is
        intentionally only for local test storage; production retrieval uses
        the same SQL scope and filters before pgvector ranks the candidates.
        """

        statement = (
            select(
                RetrievalChunkRecord,
                RetrievalIndexBuildRecord,
                AgreementRecord,
                RetrievalChunkEmbeddingRecord,
            )
            .join(
                RetrievalIndexBuildRecord,
                and_(
                    RetrievalChunkRecord.build_id == RetrievalIndexBuildRecord.id,
                    RetrievalChunkRecord.organization_id
                    == RetrievalIndexBuildRecord.organization_id,
                    RetrievalChunkRecord.workspace_id == RetrievalIndexBuildRecord.workspace_id,
                    RetrievalChunkRecord.agreement_id == RetrievalIndexBuildRecord.agreement_id,
                ),
            )
            .join(AgreementRecord, RetrievalChunkRecord.agreement_id == AgreementRecord.id)
            .join(
                RetrievalChunkEmbeddingRecord,
                and_(
                    RetrievalChunkEmbeddingRecord.organization_id
                    == RetrievalChunkRecord.organization_id,
                    RetrievalChunkEmbeddingRecord.workspace_id == RetrievalChunkRecord.workspace_id,
                    RetrievalChunkEmbeddingRecord.agreement_id == RetrievalChunkRecord.agreement_id,
                    RetrievalChunkEmbeddingRecord.build_id == RetrievalChunkRecord.build_id,
                    RetrievalChunkEmbeddingRecord.chunk_id == RetrievalChunkRecord.chunk_id,
                ),
            )
            .where(RetrievalChunkRecord.organization_id == organization_id)
            .where(RetrievalChunkRecord.workspace_id == workspace_id)
            .where(RetrievalIndexBuildRecord.state == "active")
            .where(AgreementRecord.archived_at.is_(None))
            .where(AgreementRecord.deletion_requested_at.is_(None))
            .where(RetrievalChunkEmbeddingRecord.organization_id == organization_id)
            .where(RetrievalChunkEmbeddingRecord.workspace_id == workspace_id)
            .where(RetrievalChunkEmbeddingRecord.index_version == index_version)
            .where(RetrievalChunkEmbeddingRecord.dimensions == dimensions)
            .where(RetrievalChunkEmbeddingRecord.configuration_version == configuration_version)
            .where(RetrievalChunkEmbeddingRecord.model == model)
            .where(RetrievalChunkEmbeddingRecord.state == "ready")
            .where(RetrievalChunkEmbeddingRecord.embedding.is_not(None))
        )
        statement = _apply_filters(statement, filters)
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            distance = RetrievalChunkEmbeddingRecord.embedding.op("<=>")(query_embedding)
            rows = self._session.execute(
                statement.order_by(distance, RetrievalChunkRecord.chunk_id).limit(limit)
            ).all()
        else:
            rows = list(self._session.execute(statement).all())
            rows.sort(
                key=lambda row: (
                    _cosine_distance(row[3].embedding or [], query_embedding),
                    row[0].chunk_id,
                )
            )
            rows = rows[:limit]
        return [
            RankedChunk(
                chunk_id=chunk.chunk_id,
                agreement_id=agreement.id,
                agreement_title=agreement.title,
                agreement_type=agreement.agreement_type,
                agreement_status=agreement.status,
                source_checksum=chunk.source_checksum,
                chunker_version=chunk.chunker_version,
                build_id=build.id,
                anchor_ids=tuple(chunk.anchor_ids),
                content=chunk.content,
                embedding_index_version=embedding.index_version,
            )
            for chunk, build, agreement, embedding in rows
        ]

    def available_embedding_spaces(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        index_version: str,
        dimensions: int,
        limit: int,
    ) -> list[EmbeddingSpace]:
        latest_update = func.max(RetrievalChunkEmbeddingRecord.updated_at)
        statement = (
            select(
                RetrievalChunkEmbeddingRecord.configuration_version,
                RetrievalChunkEmbeddingRecord.model,
                latest_update.label("latest_update"),
            )
            .join(
                RetrievalChunkRecord,
                and_(
                    RetrievalChunkEmbeddingRecord.organization_id
                    == RetrievalChunkRecord.organization_id,
                    RetrievalChunkEmbeddingRecord.workspace_id == RetrievalChunkRecord.workspace_id,
                    RetrievalChunkEmbeddingRecord.agreement_id == RetrievalChunkRecord.agreement_id,
                    RetrievalChunkEmbeddingRecord.build_id == RetrievalChunkRecord.build_id,
                    RetrievalChunkEmbeddingRecord.chunk_id == RetrievalChunkRecord.chunk_id,
                ),
            )
            .join(
                RetrievalIndexBuildRecord,
                and_(
                    RetrievalChunkRecord.build_id == RetrievalIndexBuildRecord.id,
                    RetrievalChunkRecord.organization_id
                    == RetrievalIndexBuildRecord.organization_id,
                    RetrievalChunkRecord.workspace_id == RetrievalIndexBuildRecord.workspace_id,
                    RetrievalChunkRecord.agreement_id == RetrievalIndexBuildRecord.agreement_id,
                ),
            )
            .join(AgreementRecord, RetrievalChunkRecord.agreement_id == AgreementRecord.id)
            .where(RetrievalChunkEmbeddingRecord.organization_id == organization_id)
            .where(RetrievalChunkEmbeddingRecord.workspace_id == workspace_id)
            .where(RetrievalChunkEmbeddingRecord.index_version == index_version)
            .where(RetrievalChunkEmbeddingRecord.dimensions == dimensions)
            .where(RetrievalChunkEmbeddingRecord.state == "ready")
            .where(RetrievalChunkEmbeddingRecord.embedding.is_not(None))
            .where(RetrievalIndexBuildRecord.state == "active")
            .where(AgreementRecord.archived_at.is_(None))
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )
        rows = self._session.execute(
            _apply_filters(statement, filters)
            .group_by(
                RetrievalChunkEmbeddingRecord.configuration_version,
                RetrievalChunkEmbeddingRecord.model,
            )
            .order_by(latest_update.desc())
            .limit(limit)
        ).all()
        return [
            EmbeddingSpace(
                configuration_version=str(configuration_version),
                model=str(model),
            )
            for configuration_version, model, _updated_at in rows
        ]


def _apply_filters[SearchRows: tuple[object, ...]](
    statement: Select[SearchRows], filters: SearchFilters
) -> Select[SearchRows]:
    if filters.agreement_type is not None:
        statement = statement.where(AgreementRecord.agreement_type == filters.agreement_type)
    if filters.status is not None:
        statement = statement.where(AgreementRecord.status == filters.status)
    if filters.source_version is not None:
        statement = statement.where(RetrievalChunkRecord.source_checksum == filters.source_version)
    if filters.agreement_ids is not None:
        statement = statement.where(AgreementRecord.id.in_(filters.agreement_ids))
    if filters.updated_after is not None:
        statement = statement.where(
            AgreementRecord.updated_at >= _as_naive_utc(filters.updated_after)
        )
    if filters.updated_before is not None:
        statement = statement.where(
            AgreementRecord.updated_at <= _as_naive_utc(filters.updated_before)
        )
    if filters.party is not None:
        # JSON path support differs across supported database dialects; a
        # portable serialized filter is still parameterized and runs only
        # after the tenant/workspace constraints above.
        statement = statement.where(
            func.lower(cast(AgreementRecord.parties, String)).contains(filters.party.lower())
        )
    return statement


def _as_naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _cosine_distance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return float("inf")
    left_norm = sqrt(sum(component * component for component in left))
    right_norm = sqrt(sum(component * component for component in right))
    if left_norm == 0 or right_norm == 0:
        return float("inf")
    similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return 1.0 - similarity
