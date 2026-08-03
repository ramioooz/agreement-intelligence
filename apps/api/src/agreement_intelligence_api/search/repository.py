from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, and_, cast, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.retrieval.models import (
    RetrievalChunkRecord,
    RetrievalIndexBuildRecord,
)
from agreement_intelligence_api.search.schemas import SearchFilters
from agreement_intelligence_api.search.service import RankedChunk


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


def _apply_filters(
    statement: Select[tuple[RetrievalChunkRecord, RetrievalIndexBuildRecord, AgreementRecord]],
    filters: SearchFilters,
) -> Select[tuple[RetrievalChunkRecord, RetrievalIndexBuildRecord, AgreementRecord]]:
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
