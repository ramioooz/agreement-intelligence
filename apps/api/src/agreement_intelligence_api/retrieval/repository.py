from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.retrieval.models import (
    RetrievalChunkRecord,
    RetrievalIndexBuildRecord,
)


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
