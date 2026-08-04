from collections.abc import Sequence
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agreement_intelligence_api.comparisons.schemas import CreateVersionComparisonRequest
from agreement_intelligence_api.comparisons.service import (
    VersionComparisonConflictError,
    VersionComparisonService,
)


class _Agreements:
    def __init__(self, versions: Sequence[SimpleNamespace]) -> None:
        self._versions = versions

    def list_versions(self, _: object) -> list[SimpleNamespace]:
        return list(self._versions)

    def get_version(self, version_id: object) -> SimpleNamespace | None:
        return next((version for version in self._versions if version.id == version_id), None)


def _service(versions: Sequence[SimpleNamespace]) -> VersionComparisonService:
    return VersionComparisonService(None, _Agreements(versions), None, None, None)  # type: ignore[arg-type]


def test_default_comparison_uses_latest_two_completed_versions() -> None:
    agreement_id = uuid4()
    versions = [
        SimpleNamespace(
            id=uuid4(), agreement_id=agreement_id, version_number=1, processing_state="completed"
        ),
        SimpleNamespace(
            id=uuid4(), agreement_id=agreement_id, version_number=2, processing_state="completed"
        ),
        SimpleNamespace(
            id=uuid4(), agreement_id=agreement_id, version_number=3, processing_state="queued"
        ),
    ]

    assert _service(versions)._resolve_versions(agreement_id, CreateVersionComparisonRequest()) == (  # noqa: SLF001
        versions[0].id,
        versions[1].id,
    )


def test_rejects_reversed_or_uncompleted_version_pair() -> None:
    agreement_id = uuid4()
    versions = [
        SimpleNamespace(
            id=uuid4(), agreement_id=agreement_id, version_number=1, processing_state="completed"
        ),
        SimpleNamespace(
            id=uuid4(), agreement_id=agreement_id, version_number=2, processing_state="queued"
        ),
    ]
    request = CreateVersionComparisonRequest(
        baseline_version_id=versions[1].id, target_version_id=versions[0].id
    )

    with pytest.raises(VersionComparisonConflictError):
        _service(versions)._resolve_versions(agreement_id, request)  # noqa: SLF001
