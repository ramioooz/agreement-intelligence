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


class _RlsLikeSession:
    def __init__(self) -> None:
        self.tenant_scoped = False

    def get(self, model: type[object], identifier: object) -> object | None:
        if model is Organization and identifier == DEMO_ORGANIZATION_ID:
            return Organization(id=DEMO_ORGANIZATION_ID, name="Demo Legal", slug="demo-legal")
        if model is Workspace and identifier == DEMO_WORKSPACE_ID and self.tenant_scoped:
            return Workspace(
                id=DEMO_WORKSPACE_ID,
                organization_id=DEMO_ORGANIZATION_ID,
                name="Agreement Repository",
                slug="agreement-repository",
            )
        return None


class _RlsLikeIdentity:
    def __init__(self) -> None:
        self.session = _RlsLikeSession()
        self.granted_roles: list[str] = []
        self.granted_workspace_memberships = 0

    def scope_organization(self, organization_id: object) -> None:
        if organization_id == DEMO_ORGANIZATION_ID:
            self.session.tenant_scoped = True

    def grant_membership(
        self, *, organization_id: object, user_id: object, role_key: object
    ) -> object:
        self.granted_roles.append(str(role_key))
        return type("Membership", (), {"id": f"membership-{len(self.granted_roles)}"})()

    def grant_workspace_membership(
        self, *, organization_id: object, membership_id: object, workspace_id: object
    ) -> object:
        self.granted_workspace_memberships += 1
        return object()


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


def test_userinfo_validated_demo_access_token_provisions_the_scoped_application_principal(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    monkeypatch.setenv("OIDC_ISSUER", "http://localhost:8080/realms/agreement-intelligence")
    monkeypatch.setenv("OIDC_INTERNAL_ISSUER", "http://keycloak:8080/realms/agreement-intelligence")
    monkeypatch.setenv("OIDC_CLIENT_ID", "agreement-intelligence-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "local-secret")
    monkeypatch.setattr(authz, "_introspect_access_token", lambda _: {"active": False})
    monkeypatch.setattr(
        authz,
        "_userinfo_claims",
        lambda _: {
            "sub": str(DEMO_REVIEWER_SUBJECT),
            "preferred_username": "legal.reviewer",
            "email": "legal.reviewer@example.test",
        },
        raising=False,
    )
    monkeypatch.setattr(
        authz,
        "_unverified_token_claims",
        lambda _: {
            "iss": "http://localhost:8080/realms/agreement-intelligence",
            "azp": "agreement-intelligence-web",
            "sub": str(DEMO_REVIEWER_SUBJECT),
        },
        raising=False,
    )
    monkeypatch.setattr(authz, "_new_session", lambda: session)

    principal = current_principal("Bearer userinfo-validated-access-token")

    identity = IdentityService(session)
    assert identity.can_access_workspace(
        principal,
        organization_id=DEMO_ORGANIZATION_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        permission=PermissionKey.AGREEMENTS_READ,
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


def test_userinfo_claims_without_expected_token_context_fail_closed(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    monkeypatch.setenv("OIDC_ISSUER", "http://localhost:8080/realms/agreement-intelligence")
    monkeypatch.setenv("OIDC_CLIENT_ID", "agreement-intelligence-web")
    monkeypatch.setattr(authz, "_introspect_access_token", lambda _: {"active": False})
    monkeypatch.setattr(
        authz,
        "_userinfo_claims",
        lambda _: {
            "sub": str(DEMO_REVIEWER_SUBJECT),
            "preferred_username": "legal.reviewer",
        },
    )
    monkeypatch.setattr(
        authz,
        "_unverified_token_claims",
        lambda _: {
            "iss": "https://untrusted.example/realms/demo",
            "azp": "agreement-intelligence-web",
            "sub": str(DEMO_REVIEWER_SUBJECT),
        },
    )
    monkeypatch.setattr(authz, "_new_session", lambda: session)

    with pytest.raises(HTTPException) as rejected:
        current_principal("Bearer userinfo-only-access-token")
    assert rejected.value.status_code == 401


def test_local_demo_membership_sets_tenant_scope_before_loading_workspace() -> None:
    from agreement_intelligence_api.identity.local_demo import ensure_local_demo_membership

    identity = _RlsLikeIdentity()
    user = type("User", (), {"id": "local-user-id"})()

    ensure_local_demo_membership(
        identity,  # type: ignore[arg-type]
        user=user,
        subject=str(DEMO_REVIEWER_SUBJECT),
        username="legal.reviewer",
    )

    assert identity.granted_roles == ["legal_reviewer", "business_user"]
    assert identity.granted_workspace_memberships == 2


def test_local_demo_membership_allows_the_seeded_username_when_keycloak_generates_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agreement_intelligence_api.identity.local_demo import ensure_local_demo_membership

    monkeypatch.setenv("DEMO_REVIEWER_SUBJECT", str(DEMO_REVIEWER_SUBJECT))
    monkeypatch.setenv("DEMO_REVIEWER_USERNAME", "legal.reviewer")
    identity = _RlsLikeIdentity()
    user = type("User", (), {"id": "local-user-id"})()

    ensure_local_demo_membership(
        identity,  # type: ignore[arg-type]
        user=user,
        subject="keycloak-generated-subject",
        username="legal.reviewer",
    )

    assert identity.granted_roles == ["legal_reviewer", "business_user"]
    assert identity.granted_workspace_memberships == 2


def test_local_demo_membership_grants_seeded_admin_platform_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agreement_intelligence_api.identity.local_demo import ensure_local_demo_membership

    monkeypatch.setenv("DEMO_ADMIN_USERNAME", "platform.admin")
    identity = _RlsLikeIdentity()
    user = type("User", (), {"id": "local-admin-id"})()

    ensure_local_demo_membership(
        identity,  # type: ignore[arg-type]
        user=user,
        subject="keycloak-generated-admin-subject",
        username="platform.admin",
    )

    assert identity.granted_roles == ["platform_admin"]
    assert identity.granted_workspace_memberships == 0


def test_local_demo_membership_ignores_unknown_users() -> None:
    from agreement_intelligence_api.identity.local_demo import ensure_local_demo_membership

    identity = _RlsLikeIdentity()
    user = type("User", (), {"id": "unknown-user-id"})()

    ensure_local_demo_membership(
        identity,  # type: ignore[arg-type]
        user=user,
        subject="unknown-subject",
        username="unknown.user",
    )

    assert identity.granted_roles == []
    assert identity.granted_workspace_memberships == 0
