from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agreement_intelligence_api.comparisons.repository import (
    SQLAlchemyVersionComparisonRepository,
)
from agreement_intelligence_api.comparisons.schemas import CreateVersionComparisonRequest
from agreement_intelligence_api.comparisons.service import (
    VersionComparisonConflictError,
    VersionComparisonService,
)
from agreement_intelligence_api.identity.authz import Principal
from sqlalchemy.exc import IntegrityError


class _Agreements:
    def __init__(
        self, versions: Sequence[SimpleNamespace], agreement: SimpleNamespace | None = None
    ) -> None:
        self._versions = versions
        self._agreement = agreement

    def get(self, _: object) -> SimpleNamespace | None:
        return self._agreement

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


def test_create_persists_processing_job_before_dependent_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    service, principal, agreement_id, organization_id, workspace_id = _create_service(
        events, monkeypatch
    )

    _, created = service.create(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        idempotency_key="comparison-order",
        request=CreateVersionComparisonRequest(),
    )

    assert created is True
    assert events.index("processing.create") < events.index("comparison.create")
    assert events[-3:] == ["processing.outbox", "session.commit", "outbox.dispatch"]


def test_create_restores_tenant_scope_before_lookup_after_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    service, principal, agreement_id, organization_id, workspace_id = _create_service(
        events, monkeypatch, fail_comparison_create=True
    )

    _, created = service.create(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        idempotency_key="comparison-conflict",
        request=CreateVersionComparisonRequest(),
    )

    assert created is False
    rollback_index = events.index("session.rollback")
    assert events[rollback_index : rollback_index + 3] == [
        "session.rollback",
        "identity.scope",
        "comparison.lookup_after_rollback",
    ]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, {}),
        (
            {"provider": "openai", "model": "test-model"},
            {"provider": "openai", "model": "test-model"},
        ),
    ],
)
def test_change_response_normalizes_provider_provenance(
    stored: dict[str, object] | None, expected: dict[str, object]
) -> None:
    record = SimpleNamespace(
        id=uuid4(),
        ordinal=1,
        alignment_kind="matched",
        baseline_element_ids=["baseline-1"],
        target_element_ids=["target-1"],
        baseline_citation_ids=["baseline-citation"],
        target_citation_ids=["target-citation"],
        word_diff=[{"operation": "equal", "text": "Agreement"}],
        confidence=0.9,
        review_required=False,
        severity="low",
        legal_concepts=["cosmetic"],
        rationale="Deterministic comparison.",
        provider_provenance=stored,
    )

    response = SQLAlchemyVersionComparisonRepository.change_response(record)  # type: ignore[arg-type]

    assert response.provider_provenance == expected


def test_change_response_adapts_worker_word_diff_without_losing_replace_semantics() -> None:
    record = SimpleNamespace(
        id=uuid4(),
        ordinal=1,
        alignment_kind="matched",
        baseline_element_ids=["baseline-1"],
        target_element_ids=["target-1"],
        baseline_citation_ids=["baseline-citation"],
        target_citation_ids=["target-citation"],
        word_diff=[
            {
                "kind": "equal",
                "baseline_tokens": "Termination requires",
                "target_tokens": "Termination requires",
            },
            {"kind": "replace", "baseline_tokens": "30", "target_tokens": "60"},
            {
                "kind": "equal",
                "baseline_tokens": "days notice.",
                "target_tokens": "days notice.",
            },
        ],
        confidence=0.9,
        review_required=True,
        severity="critical",
        legal_concepts=["termination", "numbers"],
        rationale="The notice period changed.",
        provider_provenance=None,
    )

    response = SQLAlchemyVersionComparisonRepository.change_response(record)  # type: ignore[arg-type]

    assert response.word_diff == [
        {"operation": "equal", "text": "Termination requires"},
        {"operation": "delete", "text": "30"},
        {"operation": "insert", "text": "60"},
        {"operation": "equal", "text": "days notice."},
    ]


def _create_service(
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_comparison_create: bool = False,
) -> tuple[VersionComparisonService, Principal, UUID, UUID, UUID]:
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    now = datetime.now(UTC)
    versions = [
        SimpleNamespace(
            id=uuid4(),
            agreement_id=agreement_id,
            version_number=index,
            processing_state="completed",
            storage_key=f"agreements/{agreement_id}/v{index}.pdf",
            checksum=f"checksum-{index}",
            content_type="application/pdf",
        )
        for index in (1, 2)
    ]
    agreement = SimpleNamespace(
        id=agreement_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    repository = _CreateRepository(events, fail_create=fail_comparison_create, now=now)
    processing = _CreateProcessing(events)
    identity = _CreateIdentity(events)

    class _Dispatcher:
        def __init__(self, **_: object) -> None:
            pass

        def dispatch_pending(self, **_: object) -> int:
            events.append("outbox.dispatch")
            return 1

    monkeypatch.setattr(
        "agreement_intelligence_api.comparisons.service.ProcessingOutboxDispatcher", _Dispatcher
    )
    return (
        VersionComparisonService(
            repository,  # type: ignore[arg-type]
            _Agreements(versions, agreement),  # type: ignore[arg-type]
            processing,  # type: ignore[arg-type]
            identity,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        ),
        Principal(user_id=uuid4()),
        agreement_id,
        organization_id,
        workspace_id,
    )


class _CreateRepository:
    def __init__(self, events: list[str], *, fail_create: bool, now: datetime) -> None:
        self._events = events
        self._fail_create = fail_create
        self._identity_lookups = 0
        self._existing = SimpleNamespace(
            id=uuid4(),
            baseline_version_id=uuid4(),
            target_version_id=uuid4(),
            analysis_version="version-comparison.v1",
            created_at=now,
        )

    def by_idempotency_key(self, *_: object) -> None:
        return None

    def by_identity(self, *_: object) -> object | None:
        self._identity_lookups += 1
        if self._identity_lookups == 1:
            return None
        self._events.append("comparison.lookup_after_rollback")
        return self._existing

    def create(self, record: object) -> object:
        self._events.append("comparison.create")
        if self._fail_create:
            raise IntegrityError("insert comparison", {}, RuntimeError("conflict"))
        return record

    @staticmethod
    def response(record: object) -> object:
        return record


class _CreateProcessing:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def create(self, record: object) -> object:
        self._events.append("processing.create")
        return record

    def enqueue_outbox(self, *_: object, **__: object) -> None:
        self._events.append("processing.outbox")


class _CreateSession:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def rollback(self) -> None:
        self._events.append("session.rollback")

    def commit(self) -> None:
        self._events.append("session.commit")


class _CreateIdentity:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.session = _CreateSession(events)

    @staticmethod
    def can_access_workspace(*_: object, **__: object) -> bool:
        return True

    def scope_organization(self, _: object) -> None:
        self._events.append("identity.scope")
