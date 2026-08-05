"""Add versioned approval policies and approval stages.

Revision ID: 20260805_0024
Revises: 20260805_0023
Create Date: 2026-08-05
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0024"
down_revision: str | None = "20260805_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

BUSINESS_APPROVER_ROLE_ID = UUID("11111111-1111-4111-8111-111111111117")
APPROVAL_POLICIES_MANAGE_PERMISSION_ID = UUID("22222222-2222-4222-8222-22222222222d")


def upgrade() -> None:
    op.create_table(
        "approval_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("agreement_family", sa.String(length=100), nullable=False),
        sa.Column("document_direction", sa.String(length=32), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), nullable=False),
        sa.Column("materiality", sa.String(length=16), nullable=False),
        sa.Column("precedence", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_approval_policies_scope_id"
        ),
    )
    op.create_index(
        "ix_approval_policies_scope_family",
        "approval_policies",
        ["organization_id", "workspace_id", "agreement_family"],
    )
    op.create_index(
        "ix_approval_policies_organization_id", "approval_policies", ["organization_id"]
    )
    op.create_index("ix_approval_policies_workspace_id", "approval_policies", ["workspace_id"])
    op.create_index(
        "ix_approval_policies_agreement_family", "approval_policies", ["agreement_family"]
    )
    op.create_table(
        "approval_policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("submitter_may_approve", sa.Boolean(), nullable=False),
        sa.Column("allow_cross_stage_same_approver", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "policy_id"],
            [
                "approval_policies.organization_id",
                "approval_policies.workspace_id",
                "approval_policies.id",
            ],
            name="fk_approval_policy_versions_scope_policy",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_approval_policy_versions_scope_id"
        ),
        sa.UniqueConstraint(
            "policy_id", "version", name="uq_approval_policy_versions_policy_version"
        ),
    )
    for column in ("organization_id", "workspace_id", "policy_id", "status"):
        op.create_index(
            f"ix_approval_policy_versions_{column}", "approval_policy_versions", [column]
        )
    op.create_index(
        "ix_approval_policy_versions_scope_status",
        "approval_policy_versions",
        ["organization_id", "workspace_id", "status"],
    )
    op.create_table(
        "approval_policy_stages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("approval_mode", sa.String(length=16), nullable=False),
        sa.Column("quorum_count", sa.Integer(), nullable=True),
        sa.Column("eligible_role_keys", sa.JSON(), nullable=False),
        sa.Column("eligible_user_ids", sa.JSON(), nullable=False),
        sa.Column("deadline_hours", sa.Integer(), nullable=True),
        sa.Column("escalation_role_key", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "policy_version_id"],
            [
                "approval_policy_versions.organization_id",
                "approval_policy_versions.workspace_id",
                "approval_policy_versions.id",
            ],
            name="fk_approval_policy_stages_scope_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_version_id", "ordinal", name="uq_approval_policy_stages_ordinal"
        ),
    )
    for column in ("organization_id", "workspace_id", "policy_version_id"):
        op.create_index(f"ix_approval_policy_stages_{column}", "approval_policy_stages", [column])
    op.create_index(
        "ix_approval_policy_stages_scope_version",
        "approval_policy_stages",
        ["organization_id", "workspace_id", "policy_version_id"],
    )
    op.create_table(
        "approval_policy_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "workspace_id", "policy_id", "policy_version_id", "actor_id"):
        op.create_index(
            f"ix_approval_policy_audit_events_{column}", "approval_policy_audit_events", [column]
        )
    op.create_index(
        "ix_approval_policy_audit_events_scope_version",
        "approval_policy_audit_events",
        ["organization_id", "workspace_id", "policy_version_id", "occurred_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_approval_policy_audit_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'approval policy audit events are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER approval_policy_audit_immutable
            BEFORE UPDATE OR DELETE ON approval_policy_audit_events
            FOR EACH ROW EXECUTE FUNCTION prevent_approval_policy_audit_mutation();
            """
        )

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
    )
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()), sa.column("key", sa.String()))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )
    op.bulk_insert(
        roles,
        [
            {
                "id": BUSINESS_APPROVER_ROLE_ID,
                "key": "business_approver",
                "name": "Business Approver",
            }
        ],
    )
    op.bulk_insert(
        permissions,
        [
            {
                "id": APPROVAL_POLICIES_MANAGE_PERMISSION_ID,
                "key": "approval_policies:manage",
            }
        ],
    )
    role_ids = {
        "platform_admin": UUID("11111111-1111-4111-8111-111111111111"),
        "legal_admin": UUID("11111111-1111-4111-8111-111111111113"),
        "business_approver": BUSINESS_APPROVER_ROLE_ID,
    }
    permission_ids = {
        "reviews:approve": UUID("22222222-2222-4222-8222-222222222229"),
        "agreements:read": UUID("22222222-2222-4222-8222-222222222225"),
        "workspaces:read": UUID("22222222-2222-4222-8222-222222222223"),
        "search:query": UUID("22222222-2222-4222-8222-22222222222b"),
        "approval_policies:manage": APPROVAL_POLICIES_MANAGE_PERMISSION_ID,
    }
    pairs = [
        ("platform_admin", "approval_policies:manage"),
        ("legal_admin", "approval_policies:manage"),
        ("business_approver", "workspaces:read"),
        ("business_approver", "agreements:read"),
        ("business_approver", "reviews:approve"),
        ("business_approver", "search:query"),
    ]
    op.bulk_insert(
        role_permissions,
        [
            {
                "id": UUID(f"33333333-3333-4333-8333-{1000 + ordinal:012d}"),
                "role_id": role_ids[role],
                "permission_id": permission_ids[permission],
            }
            for ordinal, (role, permission) in enumerate(pairs, start=1)
        ],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS approval_policy_audit_immutable ON approval_policy_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_approval_policy_audit_mutation")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id = '22222222-2222-4222-8222-22222222222d'"
    )
    op.execute("DELETE FROM permissions WHERE id = '22222222-2222-4222-8222-22222222222d'")
    op.execute(
        "DELETE FROM role_permissions WHERE role_id = '11111111-1111-4111-8111-111111111117'"
    )
    op.execute("DELETE FROM roles WHERE id = '11111111-1111-4111-8111-111111111117'")
    op.drop_table("approval_policy_audit_events")
    op.drop_table("approval_policy_stages")
    op.drop_table("approval_policy_versions")
    op.drop_table("approval_policies")
