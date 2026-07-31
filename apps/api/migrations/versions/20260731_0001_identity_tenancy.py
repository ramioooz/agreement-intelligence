"""Create application-owned identity and tenant authorization tables.

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_ROWS = [
    ("11111111-1111-4111-8111-111111111111", "platform_admin", "Platform Admin"),
    ("11111111-1111-4111-8111-111111111112", "organization_admin", "Organization Admin"),
    ("11111111-1111-4111-8111-111111111113", "legal_admin", "Legal Admin"),
    ("11111111-1111-4111-8111-111111111114", "legal_reviewer", "Legal Reviewer"),
    ("11111111-1111-4111-8111-111111111115", "business_user", "Business User"),
    ("11111111-1111-4111-8111-111111111116", "auditor", "Auditor"),
]

PERMISSION_ROWS = [
    ("22222222-2222-4222-8222-222222222221", "members:manage"),
    ("22222222-2222-4222-8222-222222222222", "workspaces:manage"),
    ("22222222-2222-4222-8222-222222222223", "workspaces:read"),
    ("22222222-2222-4222-8222-222222222224", "agreements:create"),
    ("22222222-2222-4222-8222-222222222225", "agreements:read"),
    ("22222222-2222-4222-8222-222222222226", "agreements:update"),
    ("22222222-2222-4222-8222-222222222227", "reviews:assign"),
    ("22222222-2222-4222-8222-222222222228", "reviews:decide"),
    ("22222222-2222-4222-8222-222222222229", "reviews:approve"),
    ("22222222-2222-4222-8222-22222222222a", "playbooks:manage"),
    ("22222222-2222-4222-8222-22222222222b", "search:query"),
    ("22222222-2222-4222-8222-22222222222c", "audit:read"),
]

ROLE_PERMISSIONS = {
    "platform_admin": {
        "members:manage",
        "workspaces:manage",
        "workspaces:read",
        "agreements:create",
        "agreements:read",
        "agreements:update",
        "reviews:assign",
        "reviews:decide",
        "reviews:approve",
        "playbooks:manage",
        "search:query",
        "audit:read",
    },
    "organization_admin": {
        "members:manage",
        "workspaces:manage",
        "workspaces:read",
        "agreements:read",
        "search:query",
        "audit:read",
    },
    "legal_admin": {
        "workspaces:read",
        "playbooks:manage",
        "reviews:assign",
        "reviews:approve",
        "agreements:read",
        "search:query",
    },
    "legal_reviewer": {
        "workspaces:read",
        "agreements:read",
        "reviews:decide",
        "search:query",
    },
    "business_user": {
        "workspaces:read",
        "agreements:create",
        "agreements:read",
        "agreements:update",
        "search:query",
    },
    "auditor": {
        "agreements:read",
        "audit:read",
        "search:query",
    },
}


def seed_authorization_catalog() -> None:
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )

    role_ids = {key: role_id for role_id, key, _name in ROLE_ROWS}
    permission_ids = {key: permission_id for permission_id, key in PERMISSION_ROWS}
    op.bulk_insert(
        roles,
        [{"id": UUID(role_id), "key": key, "name": name} for role_id, key, name in ROLE_ROWS],
    )
    op.bulk_insert(
        permissions,
        [{"id": UUID(permission_id), "key": key} for permission_id, key in PERMISSION_ROWS],
    )
    rows = []
    row_number = 1
    for role_key, permission_keys in ROLE_PERMISSIONS.items():
        for permission_key in sorted(permission_keys):
            rows.append(
                {
                    "id": UUID(f"33333333-3333-4333-8333-{row_number:012d}"),
                    "role_id": UUID(role_ids[role_key]),
                    "permission_id": UUID(permission_ids[permission_key]),
                }
            )
            row_number += 1
    op.bulk_insert(role_permissions, rows)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("oidc_issuer", sa.String(length=512), nullable=False),
        sa.Column("oidc_subject", sa.String(length=512), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject"),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "key",
            sa.Enum(
                "platform_admin",
                "organization_admin",
                "legal_admin",
                "legal_reviewer",
                "business_user",
                "auditor",
                name="rolekey",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "key",
            sa.Enum(
                "members:manage",
                "workspaces:manage",
                "workspaces:read",
                "agreements:create",
                "agreements:read",
                "agreements:update",
                "reviews:assign",
                "reviews:decide",
                "reviews:approve",
                "playbooks:manage",
                "search:query",
                "audit:read",
                name="permissionkey",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug"),
    )
    op.create_index("ix_workspaces_organization_id", "workspaces", ["organization_id"])
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", "role_id"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "membership_id"),
    )
    op.create_index(
        "ix_workspace_memberships_membership_id", "workspace_memberships", ["membership_id"]
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"]
    )
    seed_authorization_catalog()


def downgrade() -> None:
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_membership_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_organization_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("role_permissions")
    op.drop_index("ix_workspaces_organization_id", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("organizations")
    op.drop_table("users")
