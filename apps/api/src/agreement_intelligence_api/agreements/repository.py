from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.models import (
    AgreementDeletionAuditEventRecord,
    AgreementRecord,
    AgreementVersionAuditEventRecord,
    AgreementVersionRecord,
)
from agreement_intelligence_api.agreements.schemas import (
    AgreementFile,
    AgreementResponse,
    AgreementVersionResponse,
)
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
    ProcessingOutboxRecord,
)


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
            current_version_id=agreement.current_version_id,
            comparison_baseline_version_id=agreement.comparison_baseline_version_id,
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
        record.current_version_id = agreement.current_version_id
        record.comparison_baseline_version_id = agreement.comparison_baseline_version_id
        record.archived_at = agreement.archived_at
        record.updated_at = agreement.updated_at
        self._session.flush()
        return self._to_response(record)

    def create_version(
        self,
        record: AgreementVersionRecord,
        *,
        actor_id: UUID,
        action: str,
    ) -> AgreementVersionResponse:
        self._session.add(record)
        self._session.flush()
        self._session.add(
            AgreementVersionAuditEventRecord(
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                agreement_id=record.agreement_id,
                version_id=record.id,
                actor_id=actor_id,
                action=action,
                metadata_json={
                    "version_number": record.version_number,
                    "checksum": record.checksum,
                },
            )
        )
        self._session.flush()
        return self.version_response(record)

    def get_version(self, version_id: UUID) -> AgreementVersionRecord | None:
        return self._session.get(AgreementVersionRecord, version_id)

    def list_versions(self, agreement_id: UUID) -> list[AgreementVersionRecord]:
        return list(
            self._session.scalars(
                select(AgreementVersionRecord)
                .where(AgreementVersionRecord.agreement_id == agreement_id)
                .order_by(AgreementVersionRecord.version_number)
            )
        )

    def version_by_idempotency_key(
        self, agreement_id: UUID, idempotency_key: str
    ) -> AgreementVersionRecord | None:
        return self._session.scalar(
            select(AgreementVersionRecord).where(
                AgreementVersionRecord.agreement_id == agreement_id,
                AgreementVersionRecord.idempotency_key == idempotency_key,
            )
        )

    def version_by_checksum(
        self, agreement_id: UUID, checksum: str
    ) -> AgreementVersionRecord | None:
        return self._session.scalar(
            select(AgreementVersionRecord).where(
                AgreementVersionRecord.agreement_id == agreement_id,
                AgreementVersionRecord.checksum == checksum,
            )
        )

    @staticmethod
    def version_response(record: AgreementVersionRecord) -> AgreementVersionResponse:
        uploaded_at = _as_aware_utc(record.uploaded_at)
        assert uploaded_at is not None
        return AgreementVersionResponse(
            id=record.id,
            agreement_id=record.agreement_id,
            organization_id=record.organization_id,
            workspace_id=record.workspace_id,
            version_number=record.version_number,
            predecessor_version_id=record.predecessor_version_id,
            file=AgreementFile(
                file_name=record.file_name,
                content_type=record.content_type,
                storage_key=record.storage_key,
                checksum=record.checksum,
                byte_size=record.byte_size,
                version_number=record.version_number,
            ),
            uploaded_by=record.uploaded_by,
            uploaded_at=uploaded_at,
            processing_state=record.processing_state,  # type: ignore[arg-type]
            processing_job_id=record.processing_job_id,
            extraction_version=record.extraction_version,
            analysis_provenance=record.analysis_provenance,
        )

    def deletion_object_keys(self, agreement: AgreementResponse) -> list[str]:
        artifact_keys = list(
            self._session.scalars(
                select(ProcessingArtifactRecord.artifact_key).where(
                    ProcessingArtifactRecord.agreement_id == agreement.id
                )
            )
        )
        referenced_source_keys = {
            source_file.get("storage_key")
            for record in self._session.scalars(
                select(AgreementRecord.files)
                .where(AgreementRecord.organization_id == agreement.organization_id)
                .where(AgreementRecord.workspace_id == agreement.workspace_id)
                .where(AgreementRecord.id != agreement.id)
            )
            for source_file in record
            if isinstance(source_file, dict) and isinstance(source_file.get("storage_key"), str)
        }
        source_keys = [
            file.storage_key
            for file in agreement.files
            if file.storage_key not in referenced_source_keys
        ]
        return [*source_keys, *artifact_keys]

    def permanently_delete(self, agreement: AgreementResponse, *, actor_id: UUID) -> None:
        self._session.add(
            AgreementDeletionAuditEventRecord(
                organization_id=agreement.organization_id,
                workspace_id=agreement.workspace_id,
                agreement_id=agreement.id,
                title=agreement.title,
                agreement_type=agreement.agreement_type,
                file_checksums=[file.checksum for file in agreement.files],
                actor_id=actor_id,
            )
        )
        self._session.execute(
            delete(ProcessingOutboxRecord).where(
                ProcessingOutboxRecord.agreement_id == agreement.id
            )
        )
        self._session.execute(
            delete(ProcessingArtifactRecord).where(
                ProcessingArtifactRecord.agreement_id == agreement.id
            )
        )
        self._session.execute(
            delete(ProcessingJobRecord).where(ProcessingJobRecord.agreement_id == agreement.id)
        )
        self._session.execute(delete(AgreementRecord).where(AgreementRecord.id == agreement.id))
        self._session.flush()

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
                "current_version_id": record.current_version_id,
                "comparison_baseline_version_id": record.comparison_baseline_version_id,
                "archived_at": _as_aware_utc(record.archived_at),
                "created_at": _as_aware_utc(record.created_at),
                "updated_at": _as_aware_utc(record.updated_at),
            }
        )


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
