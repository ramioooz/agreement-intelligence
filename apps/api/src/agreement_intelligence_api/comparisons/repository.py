from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.access import active_agreement_statement
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.comparisons.models import (
    VersionComparisonChangeRecord,
    VersionComparisonRunRecord,
)
from agreement_intelligence_api.comparisons.schemas import (
    VersionComparisonChangeResponse,
    VersionComparisonResultResponse,
    VersionComparisonRunResponse,
)


class SQLAlchemyVersionComparisonRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, record: VersionComparisonRunRecord) -> VersionComparisonRunResponse:
        active = self._session.scalar(
            active_agreement_statement(
                record.agreement_id,
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                for_update=True,
            )
        )
        if active is None:
            raise RuntimeError("cannot compare a deleted agreement")
        self._session.add(record)
        self._session.flush()
        return self.response(record)

    def get(self, comparison_id: UUID) -> VersionComparisonRunRecord | None:
        return self._session.scalar(
            select(VersionComparisonRunRecord)
            .join(AgreementRecord, VersionComparisonRunRecord.agreement_id == AgreementRecord.id)
            .where(VersionComparisonRunRecord.id == comparison_id)
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )

    def by_identity(
        self,
        agreement_id: UUID,
        baseline_version_id: UUID,
        target_version_id: UUID,
        analysis_version: str,
    ) -> VersionComparisonRunRecord | None:
        return self._session.scalar(
            select(VersionComparisonRunRecord)
            .join(AgreementRecord, VersionComparisonRunRecord.agreement_id == AgreementRecord.id)
            .where(
                VersionComparisonRunRecord.agreement_id == agreement_id,
                VersionComparisonRunRecord.baseline_version_id == baseline_version_id,
                VersionComparisonRunRecord.target_version_id == target_version_id,
                VersionComparisonRunRecord.analysis_version == analysis_version,
                AgreementRecord.deletion_requested_at.is_(None),
            )
        )

    def by_idempotency_key(
        self, agreement_id: UUID, idempotency_key: str
    ) -> VersionComparisonRunRecord | None:
        return self._session.scalar(
            select(VersionComparisonRunRecord)
            .join(AgreementRecord, VersionComparisonRunRecord.agreement_id == AgreementRecord.id)
            .where(
                VersionComparisonRunRecord.agreement_id == agreement_id,
                VersionComparisonRunRecord.idempotency_key == idempotency_key,
                AgreementRecord.deletion_requested_at.is_(None),
            )
        )

    def list_changes(self, comparison_id: UUID) -> list[VersionComparisonChangeResponse]:
        return [
            self.change_response(record)
            for record in self._session.scalars(
                select(VersionComparisonChangeRecord)
                .join(
                    VersionComparisonRunRecord,
                    VersionComparisonChangeRecord.comparison_run_id
                    == VersionComparisonRunRecord.id,
                )
                .join(
                    AgreementRecord,
                    VersionComparisonRunRecord.agreement_id == AgreementRecord.id,
                )
                .where(VersionComparisonChangeRecord.comparison_run_id == comparison_id)
                .where(AgreementRecord.deletion_requested_at.is_(None))
                .order_by(VersionComparisonChangeRecord.ordinal)
            )
        ]

    def result(self, record: VersionComparisonRunRecord) -> VersionComparisonResultResponse:
        return VersionComparisonResultResponse(
            **self.response(record).model_dump(), changes=self.list_changes(record.id)
        )

    @staticmethod
    def response(record: VersionComparisonRunRecord) -> VersionComparisonRunResponse:
        return VersionComparisonRunResponse(
            id=record.id,
            agreement_id=record.agreement_id,
            baseline_version_id=record.baseline_version_id,
            target_version_id=record.target_version_id,
            processing_job_id=record.processing_job_id,
            analysis_version=record.analysis_version,
            state=record.state,  # type: ignore[arg-type]
            failure_category=record.failure_category,
            failure_message=record.failure_message,
            analysis_provenance=record.analysis_provenance,
            created_at=_aware(record.created_at),
            updated_at=_aware(record.updated_at),
            completed_at=_aware_optional(record.completed_at),
        )

    @staticmethod
    def change_response(record: VersionComparisonChangeRecord) -> VersionComparisonChangeResponse:
        return VersionComparisonChangeResponse(
            id=record.id,
            ordinal=record.ordinal,
            alignment_kind=record.alignment_kind,
            baseline_element_ids=record.baseline_element_ids,
            target_element_ids=record.target_element_ids,
            baseline_citation_ids=record.baseline_citation_ids,
            target_citation_ids=record.target_citation_ids,
            word_diff=_render_word_diff(record.word_diff),
            confidence=record.confidence,
            review_required=record.review_required,
            severity=record.severity,
            legal_concepts=record.legal_concepts,
            rationale=record.rationale,
            provider_provenance=record.provider_provenance or {},
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


def _render_word_diff(parts: list[dict[str, str]]) -> list[dict[str, str]]:
    rendered: list[dict[str, str]] = []
    for part in parts:
        operation = part.get("operation")
        text = part.get("text")
        if operation in {"equal", "insert", "delete"} and text:
            rendered.append({"operation": operation, "text": text})
            continue

        kind = part.get("kind")
        baseline = part.get("baseline_tokens", "")
        target = part.get("target_tokens", "")
        if kind == "equal" and (baseline or target):
            rendered.append({"operation": "equal", "text": baseline or target})
        elif kind == "delete" and baseline:
            rendered.append({"operation": "delete", "text": baseline})
        elif kind == "insert" and target:
            rendered.append({"operation": "insert", "text": target})
        elif kind == "replace":
            if baseline:
                rendered.append({"operation": "delete", "text": baseline})
            if target:
                rendered.append({"operation": "insert", "text": target})
    return rendered
