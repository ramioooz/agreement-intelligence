"""Deterministic local-development tenancy, granted only after OIDC validation."""

from os import environ
from uuid import UUID

from agreement_intelligence_api.identity.models import Organization, User, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService

DEMO_ORGANIZATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEMO_WORKSPACE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DEMO_REVIEWER_SUBJECT = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def ensure_local_demo_membership(
    identity: IdentityService, *, user: User, subject: str, username: str | None = None
) -> None:
    """Grant the configured local demo reviewer its application-owned access.

    This bridge never derives roles or scope from bearer-token claims. It only
    recognizes one explicitly configured, introspected local development user.
    """
    configured_subject = environ.get("DEMO_REVIEWER_SUBJECT", str(DEMO_REVIEWER_SUBJECT))
    configured_username = environ.get("DEMO_REVIEWER_USERNAME", "legal.reviewer")
    if subject != configured_subject and username != configured_username:
        return
    identity.scope_organization(DEMO_ORGANIZATION_ID)
    organization = identity.session.get(Organization, DEMO_ORGANIZATION_ID)
    workspace = identity.session.get(Workspace, DEMO_WORKSPACE_ID)
    if organization is None or workspace is None or workspace.organization_id != organization.id:
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
