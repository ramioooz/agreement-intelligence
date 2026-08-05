from collections.abc import Callable, Generator
from uuid import UUID, uuid4

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


@fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
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


def _policy_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "UAE client approval",
        "agreement_family": "client_agreement",
        "jurisdiction": "UAE",
        "stages": [
            {
                "name": "Legal approval",
                "approval_mode": "all",
                "eligible_role_keys": ["legal_admin"],
            },
            {
                "name": "Business approval",
                "approval_mode": "quorum",
                "quorum_count": 1,
                "eligible_role_keys": ["business_approver"],
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_legal_admin_creates_draft_policy_with_separation_defaults(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_scope(session, RoleKey.LEGAL_ADMIN)

    response = client_for_session(user_id).post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["submitter_may_approve"] is False
    assert payload["allow_cross_stage_same_approver"] is False
    assert [stage["ordinal"] for stage in payload["stages"]] == [1, 2]


def test_publication_rejects_impossible_quorum(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_scope(session, RoleKey.LEGAL_ADMIN)
    client = client_for_session(user_id)
    created = client.post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(
            stages=[
                {
                    "name": "Business approval",
                    "approval_mode": "quorum",
                    "quorum_count": 2,
                    "eligible_role_keys": ["business_approver"],
                }
            ]
        ),
    ).json()

    published = client.post(
        f"/approval-policies/{created['policy_id']}/versions/1/publish",
        params=_scope_query(organization, workspace),
    )

    assert published.status_code == 422
    assert published.json()["detail"]["code"] == "invalid_approval_policy_draft"


def test_routing_prefers_specific_scope_and_rejects_equal_published_match(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_scope(session, RoleKey.LEGAL_ADMIN)
    client = client_for_session(user_id)
    general = client.post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(name="Global client approval", jurisdiction="any", precedence=100),
    ).json()
    regional = client.post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(name="UAE client approval", jurisdiction="UAE", precedence=100),
    ).json()
    duplicate = client.post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(name="Duplicate UAE approval", jurisdiction="UAE", precedence=100),
    ).json()

    assert (
        client.post(
            f"/approval-policies/{general['policy_id']}/versions/1/publish",
            params=_scope_query(organization, workspace),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/approval-policies/{regional['policy_id']}/versions/1/publish",
            params=_scope_query(organization, workspace),
        ).status_code
        == 200
    )

    conflict = client.post(
        f"/approval-policies/{duplicate['policy_id']}/versions/1/publish",
        params=_scope_query(organization, workspace),
    )
    routed = client.get(
        "/approval-policies/route",
        params={
            **_scope_query(organization, workspace),
            "agreement_family": "client_agreement",
            "jurisdiction": "UAE",
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "approval_policy_routing_conflict"
    assert routed.status_code == 200
    assert routed.json()["policy_id"] == regional["policy_id"]


def test_publication_rejects_overlapping_scopes_that_would_tie_at_routing(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_scope(session, RoleKey.LEGAL_ADMIN)
    client = client_for_session(user_id)
    direction_specific = client.post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(
            name="Counterparty client approval",
            document_direction="counterparty",
            jurisdiction="any",
            precedence=100,
        ),
    ).json()
    jurisdiction_specific = client.post(
        "/approval-policies",
        params=_scope_query(organization, workspace),
        json=_policy_payload(
            name="UAE client approval",
            document_direction="any",
            jurisdiction="UAE",
            precedence=100,
        ),
    ).json()

    assert (
        client.post(
            f"/approval-policies/{direction_specific['policy_id']}/versions/1/publish",
            params=_scope_query(organization, workspace),
        ).status_code
        == 200
    )

    conflict = client.post(
        f"/approval-policies/{jurisdiction_specific['policy_id']}/versions/1/publish",
        params=_scope_query(organization, workspace),
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "approval_policy_routing_conflict"
