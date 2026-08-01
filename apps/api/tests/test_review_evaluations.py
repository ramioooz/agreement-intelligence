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
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from fastapi.testclient import TestClient
from pytest import fixture
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
    _complete_analysis(session, agreement, organization, workspace)
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
    assert payload["analysis_version"] == "document-analysis.v1"
    assert payload["extraction_version"] == "clause-rules.v1"
    assert payload["findings"] == [
        {
            "id": payload["findings"][0]["id"],
            "rule_id": playbook["rules"][0]["id"],
            "result": "satisfied",
            "severity": "high",
            "confidence": 0.91,
            "method": "deterministic",
            "citation_ids": ["citation-liability"],
            "playbook_version_id": playbook["id"],
            "extraction_version": "clause-rules.v1",
            "review_state": "unreviewed",
        }
    ]
    assert listed.status_code == 200
    assert listed.json() == [payload]


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


class _Storage:
    def __init__(self, manifest: dict[str, object]) -> None:
        self._manifest = manifest

    def read(self, _: str) -> Any:
        import json

        from agreement_intelligence_api.documents.storage import StoredDocument

        return StoredDocument(
            content=json.dumps(self._manifest).encode(), content_type="application/json"
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
    client: TestClient, organization: Organization, workspace: Workspace
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
                    "policy_type": "required",
                    "preferred_language": "liability is capped at fees paid",
                    "fallback_language": None,
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
    session: Session, agreement: dict[str, Any], organization: Organization, workspace: Workspace
) -> None:
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
            job_id=job.id, agreement_id=job.agreement_id, artifact_key="analysis/manifest.json"
        )
    )
    session.commit()


def _analysis_manifest() -> dict[str, object]:
    return {
        "schema_version": "document-analysis.v1",
        "clauses": [
            {
                "category": "limitation_of_liability",
                "source_text": "Liability is capped at fees paid in the prior 12 months.",
                "confidence": 0.91,
                "citation_anchor_ids": ["citation-liability"],
                "extraction_version": "clause-rules.v1",
            }
        ],
    }
