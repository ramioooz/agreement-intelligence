from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.playbooks.models import PlaybookRuleRecord
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from agreement_intelligence_api.reviews.models import PlaybookFindingRecord
from agreement_intelligence_api.reviews.schemas import SubmitPlaybookEvaluationRequest
from agreement_intelligence_api.reviews.service import PlaybookEvaluationService, _evaluate
from fastapi.testclient import TestClient
from pytest import fixture, mark
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@fixture
def client_for_session(session: Session) -> Generator[Callable[[UUID], TestClient]]:
    app.dependency_overrides[get_session] = lambda: session

    def build_client(user_id: UUID) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
        return TestClient(app)

    try:
        yield build_client
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "document_storage"):
            del app.state.document_storage


def test_manual_evaluation_prefers_deterministic_clause_over_provider_enrichment() -> None:
    rule = PlaybookRuleRecord(
        clause_type="limitation_of_liability",
        policy_type="required",
        preferred_language="fees paid",
    )
    analysis = {
        "clauses": [
            {
                "category": "limitation_of_liability",
                "source_text": "Liability is capped at fees paid.",
                "confidence": 0.91,
                "citation_anchor_ids": ["citation-deterministic"],
                "extraction_version": "clause-rules.v1",
            },
            {
                "category": "limitation_of_liability",
                "source_text": "Liability terms require review.",
                "confidence": 1.0,
                "citation_anchor_ids": ["citation-provider"],
                "extraction_version": "provider-hybrid.v1",
            },
        ]
    }

    _, result, confidence, citations, method, extraction_version = _evaluate(rule, analysis)

    assert result.value == "satisfied"
    assert confidence == 0.91
    assert citations == ["citation-deterministic"]
    assert method == "deterministic"
    assert extraction_version == "clause-rules.v1"


def test_manual_evaluation_keeps_review_for_unrecognized_clause_provenance() -> None:
    rule = PlaybookRuleRecord(
        clause_type="termination",
        policy_type="required",
        preferred_language="either party may terminate",
    )
    clause = {
        "category": "termination",
        "source_text": "Either party may terminate with 30 days' notice.",
        "confidence": 1.0,
        "citation_anchor_ids": ["citation-provider"],
    }

    for extraction_version in ("provider-hybrid.v1", "provider-hybrid.v2", None):
        candidate = dict(clause)
        if extraction_version is not None:
            candidate["extraction_version"] = extraction_version

        _, result, confidence, citations, method, version = _evaluate(
            rule, {"clauses": [candidate]}
        )

        assert result.value == "needs_review"
        assert confidence == 0.0
        assert citations == []
        assert method == "deterministic"
        assert version == "unknown"


def test_reviewer_submits_and_reads_a_scoped_evaluation_with_provenance(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(client, organization, workspace)
    processing_job_id = _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(_analysis_manifest())

    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    )
    listed = client.get(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
    )

    assert submitted.status_code == 201
    payload = submitted.json()
    assert payload["state"] == "completed"
    assert payload["playbook_version_id"] == playbook["id"]
    assert payload["processing_job_id"] == str(processing_job_id)
    assert payload["analysis_version"] == "document-analysis.v1"
    assert payload["extraction_version"] == "clause-rules.v1"
    assert payload["findings"] == [
        {
            "id": payload["findings"][0]["id"],
            "rule_id": playbook["rules"][0]["id"],
            "rule_title": "Liability cap",
            "clause_type": "limitation_of_liability",
            "reviewer_guidance": "Escalate uncapped liability.",
            "result": "satisfied",
            "severity": "high",
            "confidence": 0.91,
            "method": "deterministic",
            "citation_ids": ["citation-liability"],
            "playbook_version_id": playbook["id"],
            "extraction_version": "clause-rules.v1",
            "review_state": "unreviewed",
            "risk": {
                "version": "playbook-risk.v1",
                "severity": "high",
                "risk_rationale": "Exposure must be capped.",
                "risk_confidence": 0.91,
                "review_status": "complete",
                "citation_ids": ["citation-liability"],
                "model_explanation": None,
            },
            "fallback_suggestions": [],
            "decision_events": [],
            "current_decision": None,
        }
    ]
    assert listed.status_code == 200
    assert listed.json() == [payload]


def test_evaluation_analysis_can_be_loaded_from_its_exact_processing_job(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(client, organization, workspace)
    evaluated_job_id = _complete_analysis(
        session,
        agreement,
        organization,
        workspace,
        artifact_key="analysis/evaluated.json",
    )
    evaluated_manifest = _analysis_manifest(source_text="Evaluated liability clause.")
    app.state.document_storage = _KeyedStorage({"analysis/evaluated.json": evaluated_manifest})
    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    )
    _complete_analysis(
        session,
        agreement,
        organization,
        workspace,
        artifact_key="analysis/newer.json",
    )
    app.state.document_storage = _KeyedStorage(
        {
            "analysis/evaluated.json": evaluated_manifest,
            "analysis/newer.json": _analysis_manifest(source_text="Newer unrelated clause."),
        }
    )

    analysis = client.get(
        f"/agreements/{agreement['id']}/analysis",
        params={
            **_scope_query(organization, workspace),
            "processing_job_id": str(evaluated_job_id),
        },
    )

    assert submitted.status_code == 201
    assert submitted.json()["processing_job_id"] == str(evaluated_job_id)
    assert analysis.status_code == 200
    assert analysis.json()["clauses"][0]["source_text"] == "Evaluated liability clause."


def test_repeated_submission_returns_the_existing_job_bound_evaluation(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(client, organization, workspace)
    processing_job_id = _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(_analysis_manifest())
    service = PlaybookEvaluationService(
        session, IdentityService(session), _Storage(_analysis_manifest())
    )
    request = SubmitPlaybookEvaluationRequest(playbook_version_id=UUID(playbook["id"]))

    first = service.submit(
        Principal(user_id=reviewer_id),
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=UUID(agreement["id"]),
        request=request,
    )
    repeated = service.submit(
        Principal(user_id=reviewer_id),
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=UUID(agreement["id"]),
        request=request,
    )

    assert repeated.id == first.id
    assert repeated.processing_job_id == processing_job_id


def test_review_submission_rejects_a_different_agreement_family(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(agreement_type="liquidity_provider_agreement"),
    ).json()
    playbook = _published_playbook(client, organization, workspace)
    _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(_analysis_manifest())

    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    )

    assert submitted.status_code == 422
    assert submitted.json()["detail"]["code"] == "playbook_family_mismatch"


def test_prohibited_rule_without_policy_language_is_not_persisted_as_satisfied(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(
        client,
        organization,
        workspace,
        policy_type="prohibited",
        preferred_language=None,
    )
    _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(_analysis_manifest())

    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    )

    assert submitted.status_code == 201
    assert submitted.json()["findings"][0]["result"] == "needs_review"


def test_review_submission_persists_the_rule_selected_fallback_for_non_compliance(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(
        client,
        organization,
        workspace,
        policy_type="prohibited",
        preferred_language="unlimited liability",
        fallback_language="Liability is capped at USD 100,000.",
    )
    _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(
        _analysis_manifest(source_text="The supplier accepts unlimited liability.")
    )

    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    )

    assert submitted.status_code == 201
    finding = submitted.json()["findings"][0]
    assert finding["result"] == "non_compliant"
    assert finding["fallback_suggestions"] == [
        {
            "version": "playbook-fallback-suggestion.v1",
            "rule_id": playbook["rules"][0]["id"],
            "playbook_version_id": playbook["id"],
            "suggested_language": "Liability is capped at USD 100,000.",
            "review_recommendation": (
                "Review the cited clause against the approved fallback language."
            ),
            "citation_ids": ["citation-liability"],
            "comparison_kind": None,
            "comparison": None,
            "ai_generated": False,
        }
    ]


@mark.parametrize(
    "tamper_case",
    [
        "suggested_language",
        "satisfied_result",
        "needs_review_result",
        "review_recommendation",
        "ai_flag",
        "policy_comparison_cap",
        "policy_comparison_should",
        "citation_ids",
        "null_payload",
        "object_payload",
        "valid_bounded_comparison",
    ],
)
def test_finding_read_discards_fallback_suggestions_that_do_not_match_authoritative_policy(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
    tamper_case: str,
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(
        client,
        organization,
        workspace,
        policy_type="prohibited",
        preferred_language="unlimited liability",
        fallback_language="Liability is capped at USD 100,000.",
    )
    _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(
        _analysis_manifest(source_text="The supplier accepts unlimited liability.")
    )
    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    ).json()
    finding = session.get(PlaybookFindingRecord, UUID(submitted["findings"][0]["id"]))
    assert finding is not None
    suggestion: dict[str, object] = dict(submitted["findings"][0]["fallback_suggestions"][0])

    if tamper_case == "suggested_language":
        suggestion["suggested_language"] = "Accept unlimited liability."
    elif tamper_case == "satisfied_result":
        finding.result = "satisfied"
    elif tamper_case == "needs_review_result":
        finding.result = "needs_review"
    elif tamper_case == "review_recommendation":
        suggestion["review_recommendation"] = "Accept the clause as written."
    elif tamper_case == "ai_flag":
        suggestion["ai_generated"] = True
    elif tamper_case == "policy_comparison_cap":
        suggestion["comparison"] = "Liability is capped at USD 1,000,000."
        suggestion["ai_generated"] = True
    elif tamper_case == "policy_comparison_should":
        suggestion["comparison"] = "The clause should impose a USD 1,000,000 liability cap."
        suggestion["ai_generated"] = True
    elif tamper_case == "citation_ids":
        suggestion["citation_ids"] = ["citation-not-in-evidence"]
    elif tamper_case == "null_payload":
        finding.fallback_suggestions = cast(list[dict[str, object]], None)
    elif tamper_case == "object_payload":
        finding.fallback_suggestions = cast(list[dict[str, object]], {"suggestion": suggestion})
    elif tamper_case == "valid_bounded_comparison":
        suggestion["comparison_kind"] = "clause_differs_from_approved_position"
        suggestion["comparison"] = "The cited clause differs from the approved position."
        suggestion["ai_generated"] = True
    else:
        raise AssertionError(f"unexpected case: {tamper_case}")
    if tamper_case not in {"null_payload", "object_payload"}:
        finding.fallback_suggestions = [suggestion]
    session.commit()

    listed = client.get(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
    )

    assert listed.status_code == 200
    assert listed.json()[0]["findings"][0]["fallback_suggestions"] == (
        [suggestion] if tamper_case == "valid_bounded_comparison" else []
    )


def test_finding_read_requires_the_canonical_review_only_suggestion_without_approved_language(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(
        client,
        organization,
        workspace,
        policy_type="prohibited",
        preferred_language="unlimited liability",
    )
    _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(
        _analysis_manifest(source_text="The supplier accepts unlimited liability.")
    )
    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    ).json()
    finding = session.get(PlaybookFindingRecord, UUID(submitted["findings"][0]["id"]))
    assert finding is not None
    rule = session.get(PlaybookRuleRecord, UUID(playbook["rules"][0]["id"]))
    assert rule is not None
    rule.preferred_language = None
    rule.fallback_language = None
    finding.result = "missing"
    finding.fallback_suggestions = [
        {
            "version": "playbook-fallback-suggestion.v1",
            "rule_id": playbook["rules"][0]["id"],
            "playbook_version_id": playbook["id"],
            "suggested_language": "Invented policy language.",
            "review_recommendation": (
                "No approved language is available; reviewer assessment is required."
            ),
            "citation_ids": ["citation-liability"],
            "comparison": None,
            "ai_generated": False,
        }
    ]
    session.commit()

    listed = client.get(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
    )

    assert listed.status_code == 200
    assert listed.json()[0]["findings"][0]["fallback_suggestions"] == []


@mark.parametrize(
    "stored_risk_payload",
    [
        {},
        {
            "version": "unknown-risk.v99",
            "severity": "low",
            "risk_rationale": "Invented policy rationale.",
            "risk_confidence": 0.1,
            "review_status": "review_required",
            "citation_ids": ["citation-not-in-evidence"],
            "model_explanation": "Invented explanation.",
            "unexpected": "field",
        },
    ],
)
def test_finding_reads_fall_back_when_persisted_risk_is_legacy_or_contradictory(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
    stored_risk_payload: dict[str, object],
) -> None:
    reviewer_id, organization, workspace = _create_scope(session)
    client = client_for_session(reviewer_id)
    agreement = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload(),
    ).json()
    playbook = _published_playbook(client, organization, workspace)
    _complete_analysis(session, agreement, organization, workspace)
    app.state.document_storage = _Storage(_analysis_manifest())
    submitted = client.post(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
        json={"playbook_version_id": playbook["id"]},
    ).json()
    finding = session.get(PlaybookFindingRecord, UUID(submitted["findings"][0]["id"]))
    assert finding is not None
    finding.risk_payload = stored_risk_payload
    session.commit()

    listed = client.get(
        f"/agreements/{agreement['id']}/playbook-evaluations",
        params=_scope_query(organization, workspace),
    )

    assert listed.status_code == 200
    assert listed.json()[0]["findings"][0]["risk"] == {
        "version": "playbook-risk.v1",
        "severity": "high",
        "risk_rationale": "The deterministic finding requires reviewer assessment.",
        "risk_confidence": 0.91,
        "review_status": "complete",
        "citation_ids": ["citation-liability"],
        "model_explanation": None,
    }


class _Storage:
    def __init__(self, manifest: dict[str, object]) -> None:
        self._manifest = manifest

    def read(self, _: str) -> Any:
        import json

        from agreement_intelligence_api.documents.storage import StoredDocument

        return StoredDocument(
            content=json.dumps(self._manifest).encode(), content_type="application/json"
        )

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        return True

    def delete(self, key: str) -> None:
        return None


class _KeyedStorage:
    def __init__(self, manifests: dict[str, dict[str, object]]) -> None:
        self._manifests = manifests

    def read(self, key: str) -> Any:
        import json

        from agreement_intelligence_api.documents.storage import StoredDocument

        manifest = self._manifests.get(key)
        if manifest is None:
            return None
        return StoredDocument(
            content=json.dumps(manifest).encode(), content_type="application/json"
        )


def _create_scope(session: Session) -> tuple[UUID, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"reviewer-{uuid4()}",
        display_name="Reviewer",
    )
    organization = identity.create_organization(name="Acme", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id, name="Commercial", slug=f"commercial-{uuid4()}"
    )
    membership = identity.grant_membership(
        organization_id=organization.id, user_id=user.id, role_key=RoleKey.PLATFORM_ADMIN
    )
    identity.grant_workspace_membership(
        organization_id=organization.id, membership_id=membership.id, workspace_id=workspace.id
    )
    session.commit()
    return user.id, organization, workspace


def _scope_query(organization: Organization, workspace: Workspace) -> dict[str, str]:
    return {"organization_id": str(organization.id), "workspace_id": str(workspace.id)}


def _agreement_payload(*, agreement_type: str = "client_agreement") -> dict[str, object]:
    return {
        "title": "Client agreement",
        "agreement_type": agreement_type,
        "status": "draft",
        "parties": [],
        "files": [],
        "processing_state": "pending",
        "audit_metadata": {},
    }


def _published_playbook(
    client: TestClient,
    organization: Organization,
    workspace: Workspace,
    *,
    policy_type: str = "required",
    preferred_language: str | None = "liability is capped at fees paid",
    fallback_language: str | None = None,
) -> dict[str, Any]:
    created = client.post(
        "/playbooks",
        params=_scope_query(organization, workspace),
        json={
            "name": "Client baseline",
            "agreement_family": "client_agreement",
            "rules": [
                {
                    "clause_type": "limitation_of_liability",
                    "title": "Liability cap",
                    "policy_type": policy_type,
                    "preferred_language": preferred_language,
                    "fallback_language": fallback_language,
                    "severity": "high",
                    "legal_rationale": "Exposure must be capped.",
                    "reviewer_guidance": "Escalate uncapped liability.",
                    "evaluation_config": {
                        "method": "deterministic",
                        "semantic_assessment_permitted": False,
                    },
                }
            ],
        },
    ).json()
    response = client.post(
        f"/playbooks/{created['playbook_id']}/versions/{created['version']}/publish",
        params=_scope_query(organization, workspace),
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def _complete_analysis(
    session: Session,
    agreement: dict[str, Any],
    organization: Organization,
    workspace: Workspace,
    *,
    artifact_key: str = "analysis/manifest.json",
) -> UUID:
    now = datetime.now(UTC)
    job = ProcessingJobRecord(
        id=uuid4(),
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=UUID(agreement["id"]),
        idempotency_key=f"analysis-{uuid4()}",
        profile="baseline",
        state="completed",
        attempt_count=1,
        queued_at=now,
        processing_started_at=now,
        completed_at=now,
    )
    session.add(job)
    session.flush()
    session.add(
        ProcessingArtifactRecord(
            job_id=job.id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=job.agreement_id,
            artifact_key=artifact_key,
            created_at=now,
        )
    )
    session.commit()
    return job.id


def _analysis_manifest(
    *, source_text: str = "Liability is capped at fees paid in the prior 12 months."
) -> dict[str, object]:
    return {
        "schema_version": "document-analysis.v1",
        "clauses": [
            {
                "category": "limitation_of_liability",
                "source_text": source_text,
                "confidence": 0.91,
                "citation_anchor_ids": ["citation-liability"],
                "extraction_version": "clause-rules.v1",
            }
        ],
    }
