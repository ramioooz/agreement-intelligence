"""Worker-side immutable comparison materialization for versioned agreements."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    select,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.sql import text

from agreement_intelligence_worker.ai_configuration import AIOperation, resolve_configuration
from agreement_intelligence_worker.document_processor import ObjectStorage
from agreement_intelligence_worker.model_gateway import ModelGateway
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    PermanentProcessingError,
    ProcessingJob,
)
from agreement_intelligence_worker.version_alignment import (
    align_versions,
    canonical_version_from_manifest,
)
from agreement_intelligence_worker.version_materiality import (
    MaterialityCandidate,
    assess_materiality_with_model,
)

_metadata = MetaData()
_versions = Table(
    "agreement_versions",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True)),
    Column("workspace_id", Uuid(as_uuid=True)),
    Column("checksum", String(255)),
    Column("storage_key", String(1024)),
)
_jobs = Table(
    "processing_jobs",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True)),
    Column("workspace_id", Uuid(as_uuid=True)),
    Column("version_id", Uuid(as_uuid=True)),
    Column("state", String(32)),
)
_artifacts = Table(
    "processing_artifacts",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True)),
    Column("workspace_id", Uuid(as_uuid=True)),
    Column("job_id", Uuid(as_uuid=True)),
    Column("artifact_key", String(500)),
    Column("created_at", DateTime(timezone=True)),
)
_runs = Table(
    "version_comparison_runs",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True)),
    Column("workspace_id", Uuid(as_uuid=True)),
    Column("baseline_version_id", Uuid(as_uuid=True)),
    Column("target_version_id", Uuid(as_uuid=True)),
    Column("processing_job_id", Uuid(as_uuid=True)),
    Column("state", String(32)),
    Column("failure_category", String(64)),
    Column("failure_message", String(500)),
    Column("analysis_provenance", JSON),
    Column("completed_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
_changes = Table(
    "version_comparison_changes",
    _metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("comparison_run_id", Uuid(as_uuid=True)),
    Column("organization_id", Uuid(as_uuid=True)),
    Column("workspace_id", Uuid(as_uuid=True)),
    Column("agreement_id", Uuid(as_uuid=True)),
    Column("ordinal", Integer),
    Column("alignment_kind", String(32)),
    Column("baseline_element_ids", JSON),
    Column("target_element_ids", JSON),
    Column("baseline_citation_ids", JSON),
    Column("target_citation_ids", JSON),
    Column("word_diff", JSON),
    Column("confidence", Float),
    Column("review_required", Boolean),
    Column("severity", String(16)),
    Column("legal_concepts", JSON),
    Column("rationale", String(2000)),
    Column("provider_provenance", JSON),
    Column("created_at", DateTime(timezone=True)),
)


class VersionComparisonProcessor:
    def __init__(
        self,
        database_url: str,
        storage: ObjectStorage,
        *,
        gateway: ModelGateway | None = None,
    ) -> None:
        self._engine = create_engine(
            database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        )
        self._storage = storage
        self._gateway = gateway

    def process(self, job: ProcessingJob) -> CompletedArtifact:
        try:
            return self._process(job)
        except PermanentProcessingError as error:
            self._mark_failed(job, str(error))
            raise

    def discard(self, artifact: CompletedArtifact) -> None:
        self._storage.delete(artifact.key)

    def _process(self, job: ProcessingJob) -> CompletedArtifact:
        with self._engine.begin() as connection:
            _set_tenant_context(connection, job)
            run = (
                connection.execute(select(_runs).where(_runs.c.processing_job_id == job.id))
                .mappings()
                .one_or_none()
            )
            if run is None:
                raise PermanentProcessingError("Version comparison run is unavailable")
            baseline = (
                connection.execute(
                    select(_versions).where(_versions.c.id == run["baseline_version_id"])
                )
                .mappings()
                .one_or_none()
            )
            target = (
                connection.execute(
                    select(_versions).where(_versions.c.id == run["target_version_id"])
                )
                .mappings()
                .one_or_none()
            )
            if baseline is None or target is None:
                raise PermanentProcessingError("Version comparison sources are unavailable")
            baseline_manifest = _manifest(
                self._storage, _artifact_key_for_version(connection, baseline["id"])
            )
            target_manifest = _manifest(
                self._storage, _artifact_key_for_version(connection, target["id"])
            )
            baseline_version = canonical_version_from_manifest(baseline_manifest)
            target_version = canonical_version_from_manifest(target_manifest)
            materiality_configuration = resolve_configuration(
                AIOperation.VERSION_MATERIALITY,
                os.environ.get("AI_CONFIGURATION_ENVIRONMENT", "local"),
                organization_id=job.organization_id,
                workspace_id=job.workspace_id,
            )
            baseline_by_id = {element.element_id: element for element in baseline_version.elements}
            target_by_id = {element.element_id: element for element in target_version.elements}
            changes: list[dict[str, object]] = []
            for ordinal, alignment in enumerate(align_versions(baseline_version, target_version)):
                old = "\n".join(baseline_by_id[key].text for key in alignment.baseline_element_ids)
                new = "\n".join(target_by_id[key].text for key in alignment.target_element_ids)
                old_citations = tuple(
                    anchor
                    for key in alignment.baseline_element_ids
                    for anchor in baseline_by_id[key].citation_anchor_ids
                )
                new_citations = tuple(
                    anchor
                    for key in alignment.target_element_ids
                    for anchor in target_by_id[key].citation_anchor_ids
                )
                change_type = "modified" if alignment.kind == "matched" else alignment.kind
                assessment = assess_materiality_with_model(
                    MaterialityCandidate(
                        change_type=change_type,
                        baseline_text=old,
                        target_text=new,
                        baseline_citation_ids=old_citations,
                        target_citation_ids=new_citations,
                        alignment_confidence=alignment.confidence,
                        review_required=alignment.review_required,
                    ),
                    gateway=self._gateway,
                    configuration=materiality_configuration,
                )
                changes.append(
                    {
                        "id": uuid4(),
                        "comparison_run_id": run["id"],
                        "organization_id": job.organization_id,
                        "workspace_id": job.workspace_id,
                        "agreement_id": job.agreement_id,
                        "ordinal": ordinal,
                        "alignment_kind": alignment.kind,
                        "baseline_element_ids": list(alignment.baseline_element_ids),
                        "target_element_ids": list(alignment.target_element_ids),
                        "baseline_citation_ids": list(old_citations),
                        "target_citation_ids": list(new_citations),
                        "word_diff": [
                            {
                                "kind": item.kind,
                                "baseline_tokens": " ".join(item.baseline_tokens),
                                "target_tokens": " ".join(item.target_tokens),
                            }
                            for item in assessment.word_diff
                        ],
                        "confidence": assessment.confidence,
                        "review_required": assessment.review_required,
                        "severity": assessment.severity,
                        "legal_concepts": list(assessment.legal_concepts),
                        "rationale": assessment.rationale,
                        "provider_provenance": assessment.provider_provenance,
                        "created_at": datetime.now(UTC),
                    }
                )
            connection.execute(_changes.delete().where(_changes.c.comparison_run_id == run["id"]))
            if changes:
                connection.execute(_changes.insert(), changes)
            provenance = dict(run["analysis_provenance"] or {})
            provenance["alignment"] = "deterministic"
            connection.execute(
                update(_runs)
                .where(_runs.c.id == run["id"])
                .values(
                    state="completed",
                    analysis_provenance=provenance,
                    completed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        return CompletedArtifact(
            job_id=job.id, key=f"comparisons/{run['id']}/version-comparison.v1.json"
        )

    def _mark_failed(self, job: ProcessingJob, reason: str) -> None:
        safe_reason = (
            "Version analysis artifacts are unavailable"
            if "artifact" in reason.lower()
            else "Version comparison could not be completed"
        )
        with self._engine.begin() as connection:
            _set_tenant_context(connection, job)
            connection.execute(
                update(_runs)
                .where(_runs.c.processing_job_id == job.id)
                .values(
                    state="failed",
                    failure_category="permanent",
                    failure_message=safe_reason,
                    updated_at=datetime.now(UTC),
                )
            )


def _manifest(storage: ObjectStorage, key: str) -> dict[str, object]:
    raw = storage.read(key)
    if raw is None:
        raise PermanentProcessingError("Version analysis artifact is unavailable")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PermanentProcessingError("Version analysis artifact is invalid") from error
    if not isinstance(value, dict):
        raise PermanentProcessingError("Version analysis artifact is invalid")
    return value


def _artifact_key_for_version(connection: Connection, version_id: object) -> str:
    job = (
        connection.execute(
            select(_jobs.c.id)
            .where(_jobs.c.version_id == version_id, _jobs.c.state == "completed")
            .order_by(_jobs.c.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if job is None:
        raise PermanentProcessingError("Version analysis artifact is unavailable")
    artifact = (
        connection.execute(
            select(_artifacts.c.artifact_key)
            .where(_artifacts.c.job_id == job["id"])
            .order_by(_artifacts.c.created_at.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if artifact is None:
        raise PermanentProcessingError("Version analysis artifact is unavailable")
    return str(artifact["artifact_key"])


def _set_tenant_context(connection: Connection, job: ProcessingJob) -> None:
    if connection.dialect.name != "postgresql":
        return
    if job.organization_id is None or job.workspace_id is None:
        raise PermanentProcessingError("Version comparison is missing tenant scope")
    connection.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(job.organization_id)},
    )
