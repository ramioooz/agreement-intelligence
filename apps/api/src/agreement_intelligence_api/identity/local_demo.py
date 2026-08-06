"""Explicit local-development identity provisioning."""

import json
from os import environ
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import select

from agreement_intelligence_api.identity.models import (
    Membership,
    Organization,
    User,
    Workspace,
    WorkspaceMembership,
)
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService

DEMO_ORGANIZATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEMO_WORKSPACE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEMO_REVIEWER_SUBJECT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
DEMO_ADMIN_SUBJECT = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
DEMO_BUSINESS_APPROVER_SUBJECT = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


def provision_local_demo_identities(
    identity: IdentityService, *, issuer: str | None = None
) -> None:
    """Provision local demo users and memberships before request handling starts."""
    configured_issuer = issuer or environ.get("OIDC_ISSUER")
    if not configured_issuer:
        raise RuntimeError("OIDC_ISSUER must be configured before demo identity provisioning")
    reviewer_username = environ.get("DEMO_REVIEWER_USERNAME", "legal.reviewer")
    admin_username = environ.get("DEMO_ADMIN_USERNAME", "platform.admin")
    business_username = environ.get("DEMO_BUSINESS_APPROVER_USERNAME", "business.approver")
    subjects = _keycloak_subjects_by_username(
        [reviewer_username, admin_username, business_username]
    )

    reviewer = identity.provision_user(
        issuer=configured_issuer,
        subject=subjects.get(reviewer_username)
        or environ.get("DEMO_REVIEWER_SUBJECT", str(DEMO_REVIEWER_SUBJECT)),
        display_name=_display_name("DEMO_REVIEWER", "Legal Reviewer"),
        email=environ.get("DEMO_REVIEWER_EMAIL", "legal.reviewer@example.test"),
    )
    admin = identity.provision_user(
        issuer=configured_issuer,
        subject=subjects.get(admin_username)
        or environ.get("DEMO_ADMIN_SUBJECT", str(DEMO_ADMIN_SUBJECT)),
        display_name=_display_name("DEMO_ADMIN", "Platform Administrator"),
        email=environ.get("DEMO_ADMIN_EMAIL", "platform.admin@example.test"),
    )
    business_approver = identity.provision_user(
        issuer=configured_issuer,
        subject=subjects.get(business_username)
        or environ.get("DEMO_BUSINESS_APPROVER_SUBJECT", str(DEMO_BUSINESS_APPROVER_SUBJECT)),
        display_name=_display_name("DEMO_BUSINESS_APPROVER", "Business Approver"),
        email=environ.get("DEMO_BUSINESS_APPROVER_EMAIL", "business.approver@example.test"),
    )
    _revoke_stale_demo_memberships(identity, users=[reviewer, admin, business_approver])
    _grant_configured_membership(identity, user=reviewer, admin_matches=False)
    _grant_configured_membership(identity, user=admin, admin_matches=True)
    _grant_configured_membership(
        identity, user=business_approver, admin_matches=False, business_matches=True
    )


def grant_local_demo_membership(
    identity: IdentityService, *, user: User, subject: str, username: str | None = None
) -> None:
    """Grant configured local demo users their application-owned access."""
    configured_subject = environ.get("DEMO_REVIEWER_SUBJECT", str(DEMO_REVIEWER_SUBJECT))
    configured_reviewer_username = environ.get("DEMO_REVIEWER_USERNAME", "legal.reviewer")
    configured_admin_username = environ.get("DEMO_ADMIN_USERNAME", "platform.admin")
    configured_admin_subject = environ.get("DEMO_ADMIN_SUBJECT", str(DEMO_ADMIN_SUBJECT))
    configured_business_subject = environ.get(
        "DEMO_BUSINESS_APPROVER_SUBJECT", str(DEMO_BUSINESS_APPROVER_SUBJECT)
    )
    configured_business_username = environ.get(
        "DEMO_BUSINESS_APPROVER_USERNAME", "business.approver"
    )
    reviewer_matches = subject == configured_subject and username == configured_reviewer_username
    admin_matches = subject == configured_admin_subject and username == configured_admin_username
    business_matches = (
        subject == configured_business_subject and username == configured_business_username
    )
    if not reviewer_matches and not admin_matches and not business_matches:
        return
    _grant_configured_membership(
        identity, user=user, admin_matches=admin_matches, business_matches=business_matches
    )


def _grant_configured_membership(
    identity: IdentityService, *, user: User, admin_matches: bool, business_matches: bool = False
) -> None:
    identity.scope_organization(DEMO_ORGANIZATION_ID)
    organization = identity.session.get(Organization, DEMO_ORGANIZATION_ID)
    workspace = identity.session.get(Workspace, DEMO_WORKSPACE_ID)
    if organization is None or workspace is None or workspace.organization_id != organization.id:
        return
    if admin_matches:
        identity.grant_membership(
            organization_id=organization.id,
            user_id=user.id,
            role_key=RoleKey.PLATFORM_ADMIN,
        )
        return
    if business_matches:
        membership = identity.grant_membership(
            organization_id=organization.id, user_id=user.id, role_key=RoleKey.BUSINESS_APPROVER
        )
        identity.grant_workspace_membership(
            organization_id=organization.id, membership_id=membership.id, workspace_id=workspace.id
        )
        return
    for role_key in (RoleKey.LEGAL_REVIEWER, RoleKey.BUSINESS_USER):
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


def _revoke_stale_demo_memberships(identity: IdentityService, *, users: list[User]) -> None:
    identity.scope_organization(DEMO_ORGANIZATION_ID)
    active_demo_users = {
        (user.oidc_issuer, user.email): user.oidc_subject for user in users if user.email
    }
    for (issuer, email), active_subject in active_demo_users.items():
        stale_memberships = list(
            identity.session.scalars(
                select(Membership)
                .join(User, User.id == Membership.user_id)
                .where(Membership.organization_id == DEMO_ORGANIZATION_ID)
                .where(User.oidc_issuer == issuer)
                .where(User.email == email)
                .where(User.oidc_subject != active_subject)
            )
        )
        for membership in stale_memberships:
            workspace_memberships = list(
                identity.session.scalars(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.organization_id == membership.organization_id,
                        WorkspaceMembership.membership_id == membership.id,
                    )
                )
            )
            for workspace_membership in workspace_memberships:
                identity.session.delete(workspace_membership)
            identity.session.delete(membership)


def _display_name(prefix: str, default: str) -> str:
    first_name = environ.get(f"{prefix}_FIRST_NAME", "").strip()
    last_name = environ.get(f"{prefix}_LAST_NAME", "").strip()
    display_name = " ".join(part for part in (first_name, last_name) if part)
    return display_name or default


def _keycloak_subjects_by_username(usernames: list[str]) -> dict[str, str]:
    server_url = environ.get("KEYCLOAK_SERVER_URL")
    realm = environ.get("KEYCLOAK_REALM")
    admin_username = environ.get("KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME")
    admin_password = environ.get("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD")
    if not server_url or not realm or not admin_username or not admin_password:
        return {}
    token = _keycloak_admin_token(
        server_url=server_url,
        username=admin_username,
        password=admin_password,
    )
    return {
        username: _keycloak_user_subject(
            server_url=server_url,
            realm=realm,
            token=token,
            username=username,
        )
        for username in usernames
    }


def _keycloak_admin_token(*, server_url: str, username: str, password: str) -> str:
    request = Request(
        f"{server_url.rstrip('/')}/realms/master/protocol/openid-connect/token",
        data=urlencode(
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - configured local Keycloak
        payload = json.load(response)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Keycloak admin token response did not include an access token")
    return token


def _keycloak_user_subject(*, server_url: str, realm: str, token: str, username: str) -> str:
    query = urlencode({"exact": "true", "username": username})
    request = Request(
        f"{server_url.rstrip('/')}/admin/realms/{realm}/users?{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - configured local Keycloak
        payload = json.load(response)
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(f"Expected exactly one Keycloak demo user named {username}")
    subject = payload[0].get("id")
    if not isinstance(subject, str) or not subject:
        raise RuntimeError(f"Keycloak demo user {username} did not include a subject")
    return subject


def main() -> None:
    """Provision local demo identities for the containerized development stack."""
    from sqlalchemy.orm import sessionmaker

    from agreement_intelligence_api.db import engine

    session = sessionmaker(bind=engine())()
    try:
        identity = IdentityService(session)
        identity.bootstrap_authorization_catalog()
        provision_local_demo_identities(identity)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
