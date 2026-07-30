from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.models import (
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
    Workspace,
    WorkspaceMembership,
)
from agreement_intelligence_api.identity.permissions import (
    ROLE_PERMISSIONS,
    PermissionKey,
    RoleKey,
    permissions_for,
)


class IdentityService:
    """Persists tenant membership and evaluates the initial authorization policy."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bootstrap_authorization_catalog(self) -> None:
        roles = {role.key: role for role in self.session.scalars(select(Role))}
        for role_key in RoleKey:
            roles.setdefault(role_key, Role(key=role_key, name=role_key.replace("_", " ").title()))
            self.session.add(roles[role_key])
        permissions = {
            permission.key: permission for permission in self.session.scalars(select(Permission))
        }
        for permission_key in PermissionKey:
            permissions.setdefault(permission_key, Permission(key=permission_key))
            self.session.add(permissions[permission_key])
        self.session.flush()

        existing = {
            (role_permission.role_id, role_permission.permission_id)
            for role_permission in self.session.scalars(select(RolePermission))
        }
        for role_key, permission_keys in ROLE_PERMISSIONS.items():
            for permission_key in permission_keys:
                pair = (roles[role_key].id, permissions[permission_key].id)
                if pair not in existing:
                    self.session.add(RolePermission(role_id=pair[0], permission_id=pair[1]))
        self.session.flush()

    def provision_user(
        self, *, issuer: str, subject: str, display_name: str, email: str | None = None
    ) -> User:
        user = self.session.scalar(
            select(User).where(User.oidc_issuer == issuer, User.oidc_subject == subject)
        )
        if user is None:
            user = User(
                oidc_issuer=issuer,
                oidc_subject=subject,
                display_name=display_name,
                email=email,
            )
            self.session.add(user)
            self.session.flush()
        return user

    def create_organization(self, *, name: str, slug: str) -> Organization:
        organization = Organization(name=name, slug=slug)
        self.session.add(organization)
        self.session.flush()
        return organization

    def create_workspace(self, *, organization_id: UUID, name: str, slug: str) -> Workspace:
        self._set_tenant_scope(organization_id)
        workspace = Workspace(organization_id=organization_id, name=name, slug=slug)
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def grant_membership(
        self, *, organization_id: UUID, user_id: UUID, role_key: RoleKey
    ) -> Membership:
        self._set_tenant_scope(organization_id)
        role = self.session.scalar(select(Role).where(Role.key == role_key))
        if role is None:
            raise RuntimeError("authorization catalog has not been bootstrapped")
        membership = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
                Membership.role_id == role.id,
            )
        )
        if membership is None:
            membership = Membership(
                organization_id=organization_id, user_id=user_id, role_id=role.id
            )
            self.session.add(membership)
            self.session.flush()
        return membership

    def grant_workspace_membership(
        self, *, organization_id: UUID, membership_id: UUID, workspace_id: UUID
    ) -> WorkspaceMembership:
        self._set_tenant_scope(organization_id)
        membership = self.session.get(Membership, membership_id)
        workspace = self.session.get(Workspace, workspace_id)
        if (
            membership is None
            or workspace is None
            or membership.organization_id != organization_id
            or workspace.organization_id != organization_id
        ):
            raise ValueError("workspace membership must remain within its organization")
        workspace_membership = self.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.membership_id == membership_id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
        )
        if workspace_membership is None:
            workspace_membership = WorkspaceMembership(
                organization_id=workspace.organization_id,
                membership_id=membership_id,
                workspace_id=workspace_id,
            )
            self.session.add(workspace_membership)
            self.session.flush()
        return workspace_membership

    def can_access_organization(
        self, principal: Principal, *, organization_id: UUID, permission: PermissionKey
    ) -> bool:
        self._set_tenant_scope(organization_id)
        memberships = self.session.scalars(
            select(Membership)
            .join(Membership.role)
            .where(
                Membership.organization_id == organization_id,
                Membership.user_id == principal.user_id,
            )
        )
        return any(permission in permissions_for(membership.role.key) for membership in memberships)

    def can_access_workspace(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        permission: PermissionKey,
    ) -> bool:
        self._set_tenant_scope(organization_id)
        workspace = self.session.get(Workspace, workspace_id)
        if workspace is None or workspace.organization_id != organization_id:
            return False
        memberships = list(
            self.session.scalars(
                select(Membership)
                .join(Membership.role)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == principal.user_id,
                )
            )
        )
        allowed_memberships = [
            membership
            for membership in memberships
            if permission in permissions_for(membership.role.key)
        ]
        if not allowed_memberships:
            return False
        if any(
            membership.role.key in {RoleKey.PLATFORM_ADMIN, RoleKey.ORGANIZATION_ADMIN}
            for membership in allowed_memberships
        ):
            return True
        membership_ids = [membership.id for membership in allowed_memberships]
        return (
            self.session.scalar(
                select(WorkspaceMembership.id).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.membership_id.in_(membership_ids),
                )
            )
            is not None
        )

    def list_workspaces_for_organization(
        self, principal: Principal, *, organization_id: UUID
    ) -> list[Workspace] | None:
        self._set_tenant_scope(organization_id)
        memberships = list(
            self.session.scalars(
                select(Membership)
                .join(Membership.role)
                .where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == principal.user_id,
                )
            )
        )
        readable_memberships = [
            membership
            for membership in memberships
            if PermissionKey.WORKSPACES_READ in permissions_for(membership.role.key)
        ]
        if not readable_memberships:
            return None
        if any(
            membership.role.key in {RoleKey.PLATFORM_ADMIN, RoleKey.ORGANIZATION_ADMIN}
            for membership in readable_memberships
        ):
            return list(
                self.session.scalars(
                    select(Workspace)
                    .where(Workspace.organization_id == organization_id)
                    .order_by(Workspace.name)
                )
            )
        membership_ids = [membership.id for membership in readable_memberships]
        return list(
            self.session.scalars(
                select(Workspace)
                .join(WorkspaceMembership)
                .where(Workspace.organization_id == organization_id)
                .where(WorkspaceMembership.membership_id.in_(membership_ids))
                .order_by(Workspace.name)
            )
        )

    def _set_tenant_scope(self, organization_id: UUID) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        self.session.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
