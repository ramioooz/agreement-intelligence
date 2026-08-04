from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agreement_intelligence_worker.processing import PermanentProcessingError
from agreement_intelligence_worker.version_comparison_processor import (
    _artifact_key_for_version,
    _artifacts,
    _jobs,
    _metadata,
)
from sqlalchemy import create_engine


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
