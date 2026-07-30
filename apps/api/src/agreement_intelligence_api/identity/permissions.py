from enum import StrEnum


class RoleKey(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    ORGANIZATION_ADMIN = "organization_admin"
    LEGAL_ADMIN = "legal_admin"
    LEGAL_REVIEWER = "legal_reviewer"
    BUSINESS_USER = "business_user"
    AUDITOR = "auditor"


class PermissionKey(StrEnum):
    MEMBERS_MANAGE = "members:manage"
    WORKSPACES_MANAGE = "workspaces:manage"
    WORKSPACES_READ = "workspaces:read"
    AGREEMENTS_CREATE = "agreements:create"
    AGREEMENTS_READ = "agreements:read"
    AGREEMENTS_UPDATE = "agreements:update"
    REVIEWS_ASSIGN = "reviews:assign"
    REVIEWS_DECIDE = "reviews:decide"
    REVIEWS_APPROVE = "reviews:approve"
    PLAYBOOKS_MANAGE = "playbooks:manage"
    SEARCH_QUERY = "search:query"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[RoleKey, frozenset[PermissionKey]] = {
    RoleKey.PLATFORM_ADMIN: frozenset(PermissionKey),
    RoleKey.ORGANIZATION_ADMIN: frozenset(
        {
            PermissionKey.MEMBERS_MANAGE,
            PermissionKey.WORKSPACES_MANAGE,
            PermissionKey.WORKSPACES_READ,
            PermissionKey.AGREEMENTS_READ,
            PermissionKey.SEARCH_QUERY,
            PermissionKey.AUDIT_READ,
        }
    ),
    RoleKey.LEGAL_ADMIN: frozenset(
        {
            PermissionKey.WORKSPACES_READ,
            PermissionKey.PLAYBOOKS_MANAGE,
            PermissionKey.REVIEWS_ASSIGN,
            PermissionKey.REVIEWS_APPROVE,
            PermissionKey.AGREEMENTS_READ,
            PermissionKey.SEARCH_QUERY,
        }
    ),
    RoleKey.LEGAL_REVIEWER: frozenset(
        {
            PermissionKey.WORKSPACES_READ,
            PermissionKey.AGREEMENTS_READ,
            PermissionKey.REVIEWS_DECIDE,
            PermissionKey.SEARCH_QUERY,
        }
    ),
    RoleKey.BUSINESS_USER: frozenset(
        {
            PermissionKey.WORKSPACES_READ,
            PermissionKey.AGREEMENTS_CREATE,
            PermissionKey.AGREEMENTS_READ,
            PermissionKey.AGREEMENTS_UPDATE,
            PermissionKey.SEARCH_QUERY,
        }
    ),
    RoleKey.AUDITOR: frozenset(
        {
            PermissionKey.AGREEMENTS_READ,
            PermissionKey.AUDIT_READ,
            PermissionKey.SEARCH_QUERY,
        }
    ),
}


def permissions_for(role_key: RoleKey) -> frozenset[PermissionKey]:
    """Return the explicit permissions granted by a role."""
    return ROLE_PERMISSIONS[role_key]
