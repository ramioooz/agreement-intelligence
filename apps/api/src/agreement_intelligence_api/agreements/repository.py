from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.agreements.schemas import AgreementResponse


class SQLAlchemyAgreementRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, agreement: AgreementResponse) -> AgreementResponse:
        record = AgreementRecord(
            id=agreement.id,
            organization_id=agreement.organization_id,
            workspace_id=agreement.workspace_id,
            title=agreement.title,
            agreement_type=agreement.agreement_type,
            status=agreement.status,
            parties=[party.model_dump(mode="json") for party in agreement.parties],
            files=[file.model_dump(mode="json") for file in agreement.files],
            processing_state=agreement.processing_state,
            audit_metadata=agreement.audit_metadata,
            audit_events=[event.model_dump(mode="json") for event in agreement.audit_events],
            archived_at=agreement.archived_at,
            created_at=agreement.created_at,
            updated_at=agreement.updated_at,
        )
        self._session.add(record)
        self._session.flush()
        return self._to_response(record)

    def get(self, agreement_id: UUID) -> AgreementResponse | None:
        record = self._session.get(AgreementRecord, agreement_id)
        if record is None:
            return None
        return self._to_response(record)

    def list_for_scope(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        *,
        query: str | None,
        agreement_type: str | None,
        status: str | None,
        include_archived: bool,
    ) -> list[AgreementResponse]:
        statement: Select[tuple[AgreementRecord]] = (
            select(AgreementRecord)
            .where(AgreementRecord.organization_id == organization_id)
            .where(AgreementRecord.workspace_id == workspace_id)
            .order_by(AgreementRecord.created_at, AgreementRecord.id)
        )
        if query is not None:
            statement = statement.where(func.lower(AgreementRecord.title).contains(query.lower()))
        if agreement_type is not None:
            statement = statement.where(AgreementRecord.agreement_type == agreement_type)
        if status is not None:
            statement = statement.where(AgreementRecord.status == status)
        if not include_archived:
            statement = statement.where(AgreementRecord.archived_at.is_(None))
        return [self._to_response(record) for record in self._session.scalars(statement)]

    def replace(self, agreement: AgreementResponse) -> AgreementResponse:
        record = self._session.get(AgreementRecord, agreement.id)
        if record is None:
            raise RuntimeError("cannot replace a missing agreement")
        record.title = agreement.title
        record.agreement_type = agreement.agreement_type
        record.status = agreement.status
        record.parties = [party.model_dump(mode="json") for party in agreement.parties]
        record.files = [file.model_dump(mode="json") for file in agreement.files]
        record.processing_state = agreement.processing_state
        record.audit_metadata = agreement.audit_metadata
        record.audit_events = [event.model_dump(mode="json") for event in agreement.audit_events]
        record.archived_at = agreement.archived_at
        record.updated_at = agreement.updated_at
        self._session.flush()
        return self._to_response(record)

    @staticmethod
    def _to_response(record: AgreementRecord) -> AgreementResponse:
        return AgreementResponse.model_validate(
            {
                "id": record.id,
                "organization_id": record.organization_id,
                "workspace_id": record.workspace_id,
                "title": record.title,
                "agreement_type": record.agreement_type,
                "status": record.status,
                "parties": record.parties,
                "files": record.files,
                "processing_state": record.processing_state,
                "audit_metadata": record.audit_metadata,
                "audit_events": record.audit_events,
                "archived_at": _as_aware_utc(record.archived_at),
                "created_at": _as_aware_utc(record.created_at),
                "updated_at": _as_aware_utc(record.updated_at),
            }
        )


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
