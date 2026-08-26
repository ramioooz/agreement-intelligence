from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.access import active_agreement_statement
from agreement_intelligence_api.agreements.models import (
    AgreementDeletionAuditEventRecord,
    AgreementDeletionObjectRecord,
    AgreementDeletionOutboxRecord,
    AgreementDeletionRequestRecord,
    AgreementRecord,
    AgreementVersionAuditEventRecord,
    AgreementVersionRecord,
    DocumentObjectRegistryRecord,
)
from agreement_intelligence_api.agreements.schemas import (
    AgreementDeletionResponse,
    AgreementFile,
    AgreementResponse,
    AgreementVersionResponse,
)
from agreement_intelligence_api.comparisons.models import VersionComparisonRunRecord
from agreement_intelligence_api.documents.service import UploadedDocument
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from agreement_intelligence_api.reviews.models import ReviewCaseRecord, ReviewFinalPackageRecord


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
        record = self._session.scalar(
            select(AgreementRecord).where(
                AgreementRecord.id == agreement_id,
                AgreementRecord.deletion_requested_at.is_(None),
            )
        )
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
            .where(AgreementRecord.deletion_requested_at.is_(None))
            .where(AgreementRecord.organization_id == organization_id)
            .where(AgreementRecord.workspace_id == workspace_id)
            .order_by(AgreementRecord.created_at.desc(), AgreementRecord.id.desc())
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
        record = self._session.scalar(
            active_agreement_statement(
                agreement.id,
                organization_id=agreement.organization_id,
                workspace_id=agreement.workspace_id,
                for_update=True,
            )
        )
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
        agreement = self._session.scalar(
            active_agreement_statement(
                record.agreement_id,
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                for_update=True,
            )
        )
        if agreement is None:
            raise RuntimeError("cannot create a version for a deleted agreement")
        self._lock_object_key(record.storage_key)
        registry = self._session.scalar(
            select(DocumentObjectRegistryRecord)
            .where(
                DocumentObjectRegistryRecord.organization_id == record.organization_id,
                DocumentObjectRegistryRecord.workspace_id == record.workspace_id,
                DocumentObjectRegistryRecord.object_key == record.storage_key,
            )
            .with_for_update()
        )
        if registry is not None and registry.state != "available":
            raise RuntimeError("source object is not available; upload it again")
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
        return self._session.scalar(
            select(AgreementVersionRecord)
            .join(AgreementRecord, AgreementVersionRecord.agreement_id == AgreementRecord.id)
            .where(AgreementVersionRecord.id == version_id)
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )

    def list_versions(self, agreement_id: UUID) -> list[AgreementVersionRecord]:
        return list(
            self._session.scalars(
                select(AgreementVersionRecord)
                .join(AgreementRecord, AgreementVersionRecord.agreement_id == AgreementRecord.id)
                .where(AgreementVersionRecord.agreement_id == agreement_id)
                .where(AgreementRecord.deletion_requested_at.is_(None))
                .order_by(AgreementVersionRecord.version_number)
            )
        )

    def version_by_idempotency_key(
        self, agreement_id: UUID, idempotency_key: str
    ) -> AgreementVersionRecord | None:
        return self._session.scalar(
            select(AgreementVersionRecord)
            .where(
                AgreementVersionRecord.agreement_id == agreement_id,
                AgreementVersionRecord.idempotency_key == idempotency_key,
            )
            .join(AgreementRecord, AgreementVersionRecord.agreement_id == AgreementRecord.id)
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )

    def version_by_checksum(
        self, agreement_id: UUID, checksum: str
    ) -> AgreementVersionRecord | None:
        return self._session.scalar(
            select(AgreementVersionRecord)
            .where(
                AgreementVersionRecord.agreement_id == agreement_id,
                AgreementVersionRecord.checksum == checksum,
            )
            .join(AgreementRecord, AgreementVersionRecord.agreement_id == AgreementRecord.id)
            .where(AgreementRecord.deletion_requested_at.is_(None))
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

    def deletion_objects(self, agreement: AgreementResponse) -> list[tuple[str, str]]:
        artifact_objects = [
            (category, artifact_key)
            for artifact_key, profile in self._session.execute(
                select(ProcessingArtifactRecord.artifact_key, ProcessingJobRecord.profile)
                .join(
                    ProcessingJobRecord,
                    ProcessingArtifactRecord.job_id == ProcessingJobRecord.id,
                )
                .where(ProcessingArtifactRecord.agreement_id == agreement.id)
            )
            if (category := _artifact_category(profile)) is not None
        ]
        version_source_keys = list(
            self._session.scalars(
                select(AgreementVersionRecord.storage_key)
                .where(AgreementVersionRecord.agreement_id == agreement.id)
                .order_by(AgreementVersionRecord.version_number)
            )
        )
        source_keys = [*version_source_keys, *(file.storage_key for file in agreement.files)]
        comparison_keys = [
            f"comparisons/{run_id}/version-comparison.v1.json"
            for run_id in self._session.scalars(
                select(VersionComparisonRunRecord.id).where(
                    VersionComparisonRunRecord.agreement_id == agreement.id
                )
            )
        ]
        package_objects = [
            (category, key)
            for manifest_key, pdf_key in self._session.execute(
                select(ReviewFinalPackageRecord.manifest_key, ReviewFinalPackageRecord.pdf_key)
                .join(ReviewCaseRecord, ReviewFinalPackageRecord.review_id == ReviewCaseRecord.id)
                .where(ReviewCaseRecord.agreement_id == agreement.id)
            )
            for category, key in (
                ("review_manifest", manifest_key),
                ("review_pdf", pdf_key),
            )
        ]
        objects = [
            *(("source", key) for key in source_keys),
            *artifact_objects,
            *(("comparison", key) for key in comparison_keys),
            *package_objects,
        ]
        return list(dict.fromkeys(objects))

    def accept_deletion(
        self, agreement: AgreementResponse, *, actor_id: UUID
    ) -> AgreementDeletionResponse:
        now = datetime.now(UTC)
        agreement_record = self._session.scalar(
            select(AgreementRecord)
            .where(AgreementRecord.id == agreement.id)
            .where(AgreementRecord.organization_id == agreement.organization_id)
            .where(AgreementRecord.workspace_id == agreement.workspace_id)
            .with_for_update()
        )
        if agreement_record is None or agreement_record.deletion_requested_at is not None:
            raise RuntimeError("agreement deletion cannot be accepted twice")
        objects = self.deletion_objects(agreement)
        deletion_record = AgreementDeletionRequestRecord(
            organization_id=agreement.organization_id,
            workspace_id=agreement.workspace_id,
            agreement_id=agreement.id,
            actor_id=actor_id,
            title=agreement.title,
            agreement_type=agreement.agreement_type,
            file_checksums=[file.checksum for file in agreement.files],
            state="accepted",
            attempt_count=0,
            retry_cycle=1,
            next_attempt_at=now,
            accepted_at=now,
            updated_at=now,
        )
        self._session.add(deletion_record)
        self._session.flush()
        self._session.add_all(
            [
                AgreementDeletionObjectRecord(
                    deletion_id=deletion_record.id,
                    organization_id=agreement.organization_id,
                    workspace_id=agreement.workspace_id,
                    agreement_id=agreement.id,
                    category=category,
                    object_key=object_key,
                    state="pending",
                    created_at=now,
                    updated_at=now,
                )
                for category, object_key in objects
            ]
        )
        self._session.add(
            AgreementDeletionAuditEventRecord(
                organization_id=agreement.organization_id,
                workspace_id=agreement.workspace_id,
                agreement_id=agreement.id,
                title=agreement.title,
                agreement_type=agreement.agreement_type,
                file_checksums=[file.checksum for file in agreement.files],
                actor_id=actor_id,
                deletion_id=deletion_record.id,
                event_type="requested",
                retry_cycle=1,
                metadata_json={"object_count": len(objects)},
            )
        )
        self._session.add(
            AgreementDeletionOutboxRecord(
                deletion_id=deletion_record.id,
                organization_id=agreement.organization_id,
                workspace_id=agreement.workspace_id,
                agreement_id=agreement.id,
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        agreement_record.deletion_requested_at = now
        agreement_record.updated_at = now
        self._session.flush()
        return self.deletion_response(deletion_record)

    def deletion_by_agreement(
        self,
        agreement_id: UUID,
        *,
        organization_id: UUID,
        workspace_id: UUID,
    ) -> AgreementDeletionRequestRecord | None:
        return self._session.scalar(
            select(AgreementDeletionRequestRecord).where(
                AgreementDeletionRequestRecord.agreement_id == agreement_id,
                AgreementDeletionRequestRecord.organization_id == organization_id,
                AgreementDeletionRequestRecord.workspace_id == workspace_id,
            )
        )

    def get_deletion(self, deletion_id: UUID) -> AgreementDeletionRequestRecord | None:
        return self._session.get(AgreementDeletionRequestRecord, deletion_id)

    def redrive_deletion(
        self, record: AgreementDeletionRequestRecord, *, actor_id: UUID
    ) -> AgreementDeletionResponse:
        locked = self._session.scalar(
            select(AgreementDeletionRequestRecord)
            .where(AgreementDeletionRequestRecord.id == record.id)
            .with_for_update()
        )
        if locked is None or locked.state != "failed":
            return self.deletion_response(locked or record)
        now = datetime.now(UTC)
        locked.state = "accepted"
        locked.retry_cycle += 1
        locked.attempt_count = 0
        locked.claim_token = None
        locked.lease_expires_at = None
        locked.next_attempt_at = now
        locked.failure_category = None
        locked.failure_message = None
        locked.failed_at = None
        locked.updated_at = now
        outbox = self._session.scalar(
            select(AgreementDeletionOutboxRecord).where(
                AgreementDeletionOutboxRecord.deletion_id == locked.id
            )
        )
        if outbox is not None:
            outbox.delivered_at = None
            outbox.lease_token = None
            outbox.lease_expires_at = None
            outbox.next_attempt_at = now
            outbox.last_error = None
            outbox.updated_at = now
        self._session.add(
            AgreementDeletionAuditEventRecord(
                organization_id=locked.organization_id,
                workspace_id=locked.workspace_id,
                agreement_id=locked.agreement_id,
                title=locked.title,
                agreement_type=locked.agreement_type,
                file_checksums=locked.file_checksums,
                actor_id=actor_id,
                deletion_id=locked.id,
                event_type="redriven",
                retry_cycle=locked.retry_cycle,
                metadata_json={},
                occurred_at=now,
            )
        )
        self._session.flush()
        return self.deletion_response(locked)

    def is_object_pending_deletion(
        self,
        object_key: str,
        *,
        organization_id: UUID,
        workspace_id: UUID,
    ) -> bool:
        matches = self._session.scalars(
            select(AgreementDeletionObjectRecord)
            .join(
                AgreementDeletionRequestRecord,
                AgreementDeletionObjectRecord.deletion_id == AgreementDeletionRequestRecord.id,
            )
            .where(
                AgreementDeletionObjectRecord.organization_id == organization_id,
                AgreementDeletionObjectRecord.workspace_id == workspace_id,
                AgreementDeletionObjectRecord.object_key == object_key,
                AgreementDeletionRequestRecord.state.in_(
                    ("accepted", "processing", "retrying", "failed")
                ),
            )
        )
        for item in matches:
            if item.category != "source":
                return True
            active_reference = self._session.scalar(
                select(AgreementVersionRecord.id)
                .join(AgreementRecord, AgreementVersionRecord.agreement_id == AgreementRecord.id)
                .where(
                    AgreementVersionRecord.storage_key == object_key,
                    AgreementVersionRecord.agreement_id != item.agreement_id,
                    AgreementVersionRecord.organization_id == organization_id,
                    AgreementVersionRecord.workspace_id == workspace_id,
                    AgreementRecord.deletion_requested_at.is_(None),
                )
                .limit(1)
            )
            if active_reference is None:
                return True
        return False

    def lock_source_object(self, object_key: str) -> None:
        self._lock_object_key(object_key)

    def record_source_upload(self, uploaded: UploadedDocument) -> None:
        now = datetime.now(UTC)
        record = self._session.scalar(
            select(DocumentObjectRegistryRecord)
            .where(
                DocumentObjectRegistryRecord.organization_id == uploaded.tenant_id,
                DocumentObjectRegistryRecord.workspace_id == uploaded.workspace_id,
                DocumentObjectRegistryRecord.object_key == uploaded.object_key,
            )
            .with_for_update()
        )
        if record is None:
            record = DocumentObjectRegistryRecord(
                organization_id=uploaded.tenant_id,
                workspace_id=uploaded.workspace_id,
                object_key=uploaded.object_key,
                checksum=uploaded.sha256,
                content_type=uploaded.content_type,
                byte_size=uploaded.byte_size,
                state="available",
                updated_at=now,
            )
            self._session.add(record)
        else:
            record.checksum = uploaded.sha256
            record.content_type = uploaded.content_type
            record.byte_size = uploaded.byte_size
            record.state = "available"
            record.updated_at = now
        self._session.flush()

    def _lock_object_key(self, object_key: str) -> None:
        if self._session.get_bind().dialect.name == "postgresql":
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:object_key, 0))"),
                {"object_key": object_key},
            )

    @staticmethod
    def deletion_response(record: AgreementDeletionRequestRecord) -> AgreementDeletionResponse:
        return AgreementDeletionResponse(
            id=record.id,
            agreement_id=record.agreement_id,
            organization_id=record.organization_id,
            workspace_id=record.workspace_id,
            state=record.state,
            attempt_count=record.attempt_count,
            failure_category=record.failure_category,
            failure_message=record.failure_message,
            accepted_at=_as_required_aware_utc(record.accepted_at),
            processing_started_at=_as_aware_utc(record.processing_started_at),
            completed_at=_as_aware_utc(record.completed_at),
            failed_at=_as_aware_utc(record.failed_at),
        )

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


def _artifact_category(profile: str) -> str | None:
    if profile == "version-comparison":
        return "comparison"
    if profile.startswith("embedding-reindex:"):
        return None
    return "analysis"


def _as_required_aware_utc(value: datetime) -> datetime:
    converted = _as_aware_utc(value)
    assert converted is not None
    return converted
