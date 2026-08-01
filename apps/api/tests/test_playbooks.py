from collections.abc import Callable, Generator
from typing import Any
from uuid import UUID, uuid4

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
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


def _scope_query(organization: Organization, workspace: Workspace) -> dict[str, str]:
    return {"organization_id": str(organization.id), "workspace_id": str(workspace.id)}


def _create_scope(session: Session, role_key: RoleKey) -> tuple[UUID, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"{role_key.value}-{uuid4()}",
        display_name=role_key.replace("_", " ").title(),
    )
    organization = identity.create_organization(name=f"Acme {uuid4()}", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Commercial",
        slug=f"commercial-{uuid4()}",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=role_key,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return user.id, organization, workspace


def _rule_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "clause_type": "limitation_of_liability",
        "title": "Limitation of liability",
        "policy_type": "required",
        "preferred_language": "Liability is capped at fees paid in the prior 12 months.",
        "fallback_language": "Liability is capped at USD 100,000.",
        "severity": "high",
        "legal_rationale": "Uncapped liability is not an approved commercial position.",
        "reviewer_guidance": "Escalate any uncapped liability language to legal counsel.",
        "evaluation_config": {"method": "deterministic", "semantic_assessment_permitted": False},
    }
    payload.update(overrides)
    return payload


def _playbook_payload(*, rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "name": "Client agreement baseline",
        "agreement_family": "client_agreement",
        "rules": [_rule_payload()] if rules is None else rules,
    }


def test_platform_admin_can_create_a_draft_playbook(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    administrator_id, organization, workspace = _create_scope(session, RoleKey.PLATFORM_ADMIN)

    response = client_for_session(administrator_id).post(
        "/playbooks",
        params=_scope_query(organization, workspace),
        json=_playbook_payload(),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["version"] == 1
    assert payload["agreement_family"] == "client_agreement"
    assert payload["rules"][0]["clause_type"] == "limitation_of_liability"
    assert payload["audit_events"][0]["action"] == "draft_created"
    assert payload["audit_events"][0]["actor_id"] == str(administrator_id)


def test_legal_admin_and_legal_reviewer_cannot_manage_playbooks(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    for role_key in (RoleKey.LEGAL_ADMIN, RoleKey.LEGAL_REVIEWER):
        user_id, organization, workspace = _create_scope(session, role_key)

        response = client_for_session(user_id).post(
            "/playbooks",
            params=_scope_query(organization, workspace),
            json=_playbook_payload(),
        )

        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "resource_not_found"}}


def test_published_playbook_rule_cannot_be_mutated(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    administrator_id, organization, workspace = _create_scope(session, RoleKey.PLATFORM_ADMIN)
    client = client_for_session(administrator_id)
    created = client.post(
        "/playbooks",
        params=_scope_query(organization, workspace),
        json=_playbook_payload(),
    )
    version = created.json()

    published = client.post(
        f"/playbooks/{version['playbook_id']}/versions/{version['version']}/publish",
        params=_scope_query(organization, workspace),
    )
    mutation = client.put(
        f"/playbooks/{version['playbook_id']}/versions/{version['version']}/rules/"
        f"{version['rules'][0]['id']}",
        params=_scope_query(organization, workspace),
        json={"severity": "critical"},
    )

    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert mutation.status_code == 409
    assert mutation.json() == {"detail": {"code": "published_playbook_immutable"}}


def test_publication_rejects_duplicate_clause_types_and_missing_policy_content(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    administrator_id, organization, workspace = _create_scope(session, RoleKey.PLATFORM_ADMIN)
    client = client_for_session(administrator_id)
    duplicate = client.post(
        "/playbooks",
        params=_scope_query(organization, workspace),
        json=_playbook_payload(
            rules=[
                _rule_payload(clause_type="Limitation Of Liability"),
                _rule_payload(clause_type="limitation of liability"),
            ]
        ),
    ).json()
    incomplete = client.post(
        "/playbooks",
        params=_scope_query(organization, workspace),
        json=_playbook_payload(rules=[_rule_payload(preferred_language="")]),
    ).json()

    duplicate_publication = client.post(
        f"/playbooks/{duplicate['playbook_id']}/versions/{duplicate['version']}/publish",
        params=_scope_query(organization, workspace),
    )
    incomplete_publication = client.post(
        f"/playbooks/{incomplete['playbook_id']}/versions/{incomplete['version']}/publish",
        params=_scope_query(organization, workspace),
    )

    assert duplicate_publication.status_code == 422
    assert duplicate_publication.json() == {
        "detail": {
            "code": "invalid_playbook_draft",
            "message": "playbook version contains duplicate clause types",
        }
    }
    assert incomplete_publication.status_code == 422
    assert incomplete_publication.json() == {
        "detail": {
            "code": "invalid_playbook_draft",
            "message": "preferred language is required for required rules",
        }
    }
