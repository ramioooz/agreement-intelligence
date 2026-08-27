import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from agreement_intelligence_worker.artifact_commit import (
    PreparedArtifact,
    write_or_read_canonical,
)
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    JobProcessor,
    PermanentProcessingError,
    ProcessingJob,
)
from agreement_intelligence_worker.version_comparison_processor import (
    VersionComparisonProcessor,
    _artifact_key_for_version,
    _artifacts,
    _changes,
    _jobs,
    _metadata,
    _runs,
    _versions,
)
from sqlalchemy import create_engine, func, select


def test_resolves_completed_analysis_artifact_not_original_source_key() -> None:
    engine = create_engine("sqlite://")
    _metadata.create_all(engine, tables=[_jobs, _artifacts])
    version_id, job_id = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            _jobs.insert().values(id=job_id, version_id=version_id, state="completed")
        )
        connection.execute(
            _artifacts.insert().values(
                id=uuid4(),
                job_id=job_id,
                artifact_key="analysis/version-1.json",
                created_at=datetime.now(UTC),
            )
        )
        assert _artifact_key_for_version(connection, version_id) == "analysis/version-1.json"


def test_missing_analysis_artifact_fails_without_reading_original_source() -> None:
    engine = create_engine("sqlite://")
    _metadata.create_all(engine, tables=[_jobs, _artifacts])
    with engine.connect() as connection, pytest.raises(PermanentProcessingError, match="artifact"):
        _artifact_key_for_version(connection, uuid4())


def test_comparison_prepares_without_mutation_and_finalizes_from_canonical_object(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'comparison.db'}"
    engine = create_engine(database_url)
    _metadata.create_all(engine)
    organization_id, workspace_id, agreement_id = uuid4(), uuid4(), uuid4()
    baseline_id, target_id, job_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    baseline_job_id, target_job_id = uuid4(), uuid4()
    baseline_key, target_key = "analysis/baseline.json", "analysis/target.json"
    with engine.begin() as connection:
        connection.execute(
            _versions.insert(),
            [
                {
                    "id": baseline_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
                {
                    "id": target_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                },
            ],
        )
        connection.execute(
            _jobs.insert(),
            [
                {"id": baseline_job_id, "version_id": baseline_id, "state": "completed"},
                {"id": target_job_id, "version_id": target_id, "state": "completed"},
            ],
        )
        connection.execute(
            _artifacts.insert(),
            [
                {"id": uuid4(), "job_id": baseline_job_id, "artifact_key": baseline_key},
                {"id": uuid4(), "job_id": target_job_id, "artifact_key": target_key},
            ],
        )
        connection.execute(
            _runs.insert().values(
                id=run_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                baseline_version_id=baseline_id,
                target_version_id=target_id,
                processing_job_id=job_id,
                state="queued",
                analysis_provenance={},
            )
        )

    def manifest(checksum: str, text: str) -> bytes:
        return json.dumps(
            {
                "source": {"checksum": checksum},
                "document": {
                    "pages": [
                        {
                            "blocks": [
                                {
                                    "anchor_id": f"citation-{checksum}",
                                    "kind": "paragraph",
                                    "text": text,
                                }
                            ]
                        }
                    ]
                },
                "clauses": [],
            }
        ).encode()

    class Storage:
        objects = {
            baseline_key: manifest("a" * 64, "Liability is capped at fees paid."),
            target_key: manifest("b" * 64, "Liability is unlimited."),
        }
        puts: list[str] = []

        def read(self, key: str) -> bytes | None:
            return self.objects.get(key)

        def put_immutable(self, key: str, content: bytes, *, content_type: str) -> bool:
            del content_type
            self.puts.append(key)
            self.objects[key] = content
            return True

        def delete(self, key: str) -> None:
            self.objects.pop(key, None)

    storage = Storage()
    job = ProcessingJob(
        id=job_id,
        agreement_id=agreement_id,
        state="processing",
        attempt_count=1,
        organization_id=organization_id,
        workspace_id=workspace_id,
        profile="version-comparison",
    )
    processor = VersionComparisonProcessor(database_url, storage)

    prepared = processor.prepare(job)

    assert prepared.artifact.key == f"comparisons/{run_id}/version-comparison.v1.json"
    assert storage.puts == []
    with engine.connect() as connection:
        assert connection.scalar(select(_runs.c.state).where(_runs.c.id == run_id)) == "queued"
        assert connection.scalar(select(func.count()).select_from(_changes)) == 0

    class CommitFenceRepository:
        claimed = False

        def claim(self, _: object) -> ProcessingJob | None:
            if self.claimed:
                return None
            self.claimed = True
            return job

        def expect(self, _: ProcessingJob, artifact: CompletedArtifact) -> bool:
            return artifact == prepared.artifact

        def commit_prepared(
            self,
            claimed_job: ProcessingJob,
            candidate: PreparedArtifact,
            *,
            finalize: Any,
        ) -> bool:
            with engine.begin() as connection:
                canonical = write_or_read_canonical(storage, candidate)
                finalize(connection, claimed_job, candidate, canonical)
            return True

    class NoRetryQueue:
        def enqueue(self, *_: object, **__: object) -> None:
            raise AssertionError("successful comparison must not retry")

    JobProcessor(cast(Any, CommitFenceRepository()), NoRetryQueue(), processor).handle(job_id)

    assert storage.puts == [f"comparisons/{run_id}/version-comparison.v1.json"]
    with engine.connect() as connection:
        assert connection.scalar(select(_runs.c.state).where(_runs.c.id == run_id)) == "completed"
        assert (connection.scalar(select(func.count()).select_from(_changes)) or 0) > 0
