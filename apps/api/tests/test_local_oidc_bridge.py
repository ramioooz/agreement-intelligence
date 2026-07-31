from collections.abc import Generator

import pytest
from agreement_intelligence_api.identity import authz
from agreement_intelligence_api.identity.authz import current_principal
from agreement_intelligence_api.identity.local_demo import (
    DEMO_ORGANIZATION_ID,
    DEMO_REVIEWER_SUBJECT,
    DEMO_WORKSPACE_ID,
)
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        identity = IdentityService(database_session)
        identity.bootstrap_authorization_catalog()
        database_session.add(
            Organization(id=DEMO_ORGANIZATION_ID, name="Demo Legal", slug="demo-legal")
        )
        database_session.add(
            Workspace(
                id=DEMO_WORKSPACE_ID,
                organization_id=DEMO_ORGANIZATION_ID,
                name="Agreement Repository",
                slug="agreement-repository",
            )
        )
        database_session.commit()
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def test_verified_demo_access_token_provisions_the_scoped_application_principal(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    monkeypatch.setenv("OIDC_ISSUER", "http://localhost:8080/realms/agreement-intelligence")
    monkeypatch.setenv("OIDC_INTERNAL_ISSUER", "http://keycloak:8080/realms/agreement-intelligence")
    monkeypatch.setenv("OIDC_CLIENT_ID", "agreement-intelligence-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "local-secret")
    monkeypatch.setattr(
        authz,
        "_introspect_access_token",
        lambda _: {
            "active": True,
            "iss": "http://localhost:8080/realms/agreement-intelligence",
            "sub": str(DEMO_REVIEWER_SUBJECT),
            "client_id": "agreement-intelligence-web",
            "preferred_username": "legal.reviewer",
            "email": "legal.reviewer@example.test",
        },
    )
    monkeypatch.setattr(authz, "_new_session", lambda: session)

    principal = current_principal("Bearer verified-access-token")

    identity = IdentityService(session)
    assert identity.can_access_workspace(
        principal,
        organization_id=DEMO_ORGANIZATION_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        permission=PermissionKey.AGREEMENTS_CREATE,
    )


def test_missing_or_unverified_tokens_fail_closed(session: Session) -> None:
    with pytest.raises(HTTPException) as missing:
        current_principal(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as malformed:
        current_principal("Bearer ")
    assert malformed.value.status_code == 401


def test_introspection_claims_from_an_unexpected_issuer_fail_closed(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    monkeypatch.setenv("OIDC_ISSUER", "http://localhost:8080/realms/agreement-intelligence")
    monkeypatch.setenv("OIDC_CLIENT_ID", "agreement-intelligence-web")
    monkeypatch.setattr(
        authz,
        "_introspect_access_token",
        lambda _: {
            "active": True,
            "iss": "https://untrusted.example/realm",
            "sub": str(DEMO_REVIEWER_SUBJECT),
            "client_id": "agreement-intelligence-web",
            "preferred_username": "legal.reviewer",
        },
    )

    with pytest.raises(HTTPException) as rejected:
        current_principal("Bearer verified-by-someone-else")
    assert rejected.value.status_code == 401
