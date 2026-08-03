from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.qa.models import QuestionThreadRecord, QuestionTurnRecord


class SQLAlchemyQuestionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_thread(self, record: QuestionThreadRecord) -> None:
        self._session.add(record)
        self._session.flush()

    def get_thread(
        self, *, organization_id: UUID, workspace_id: UUID, thread_id: UUID
    ) -> QuestionThreadRecord | None:
        return self._session.scalar(
            select(QuestionThreadRecord).where(
                QuestionThreadRecord.id == thread_id,
                QuestionThreadRecord.organization_id == organization_id,
                QuestionThreadRecord.workspace_id == workspace_id,
            )
        )

    def add_turn(self, record: QuestionTurnRecord) -> None:
        self._session.add(record)
        self._session.flush()

    def list_turns(
        self, *, organization_id: UUID, workspace_id: UUID, thread_id: UUID
    ) -> list[QuestionTurnRecord]:
        return list(
            self._session.scalars(
                select(QuestionTurnRecord)
                .where(
                    QuestionTurnRecord.organization_id == organization_id,
                    QuestionTurnRecord.workspace_id == workspace_id,
                    QuestionTurnRecord.thread_id == thread_id,
                )
                .order_by(QuestionTurnRecord.created_at, QuestionTurnRecord.id)
            )
        )
