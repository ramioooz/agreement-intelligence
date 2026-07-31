"""Enforce organization-scoped tenant isolation.

Revision ID: 20260731_0003
Revises: 20260731_0002
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0003"
down_revision: str | None = "20260731_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("workspaces", "memberships", "workspace_memberships", "agreements")

TENANT_RLS_STATEMENTS = (
    """
    ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
    ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation_workspaces ON workspaces
        FOR ALL
        USING (organization_id = current_setting('app.organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid);
    """,
    """
    ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
    ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation_memberships ON memberships
        FOR ALL
        USING (organization_id = current_setting('app.organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid);
    """,
    """
    ALTER TABLE workspace_memberships ENABLE ROW LEVEL SECURITY;
    ALTER TABLE workspace_memberships FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation_workspace_memberships ON workspace_memberships
        FOR ALL
        USING (organization_id = current_setting('app.organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid);
    """,
    """
    ALTER TABLE agreements ENABLE ROW LEVEL SECURITY;
    ALTER TABLE agreements FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation_agreements ON agreements
        FOR ALL
        USING (organization_id = current_setting('app.organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid);
    """,
)


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.create_unique_constraint(
            "uq_workspaces_organization_id_id", ["organization_id", "id"]
        )
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.create_unique_constraint(
            "uq_memberships_organization_id_id", ["organization_id", "id"]
        )
    with op.batch_alter_table("workspace_memberships") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Uuid(), nullable=True))

    _reject_legacy_cross_tenant_workspace_memberships()

    op.execute(
        """
        UPDATE workspace_memberships
        SET organization_id = (
            SELECT organization_id
            FROM workspaces
            WHERE workspaces.id = workspace_memberships.workspace_id
        )
        """
    )

    with op.batch_alter_table("workspace_memberships") as batch_op:
        batch_op.alter_column("organization_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_workspace_memberships_organization_workspace",
            "workspaces",
            ["organization_id", "workspace_id"],
            ["organization_id", "id"],
        )
        batch_op.create_foreign_key(
            "fk_workspace_memberships_organization_membership",
            "memberships",
            ["organization_id", "membership_id"],
            ["organization_id", "id"],
        )
        batch_op.create_index(
            "ix_workspace_memberships_organization_id", ["organization_id"], unique=False
        )
    with op.batch_alter_table("agreements") as batch_op:
        batch_op.create_foreign_key(
            "fk_agreements_organization_workspace",
            "workspaces",
            ["organization_id", "workspace_id"],
            ["organization_id", "id"],
        )

    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_tenant_isolation()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _disable_postgresql_tenant_isolation()

    with op.batch_alter_table("agreements") as batch_op:
        batch_op.drop_constraint("fk_agreements_organization_workspace", type_="foreignkey")
    with op.batch_alter_table("workspace_memberships") as batch_op:
        batch_op.drop_index("ix_workspace_memberships_organization_id")
        batch_op.drop_constraint(
            "fk_workspace_memberships_organization_membership", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_workspace_memberships_organization_workspace", type_="foreignkey"
        )
        batch_op.drop_column("organization_id")
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("uq_memberships_organization_id_id", type_="unique")
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("uq_workspaces_organization_id_id", type_="unique")


def _enable_postgresql_tenant_isolation() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_organization_id_change() RETURNS trigger AS $$
        BEGIN
            IF OLD.organization_id IS DISTINCT FROM NEW.organization_id THEN
                RAISE EXCEPTION 'organization_id is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for statement in TENANT_RLS_STATEMENTS:
        op.execute(statement)
    for table_name in TENANT_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER prevent_{table_name}_organization_change
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_organization_id_change();
            """
        )


def _disable_postgresql_tenant_isolation() -> None:
    for table_name in TENANT_TABLES:
        op.execute(f"DROP TRIGGER prevent_{table_name}_organization_change ON {table_name}")
        op.execute(f"DROP POLICY tenant_isolation_{table_name} ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION prevent_organization_id_change()")


def _reject_legacy_cross_tenant_workspace_memberships() -> None:
    conflict_count = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT COUNT(*)
            FROM workspace_memberships
            JOIN workspaces ON workspaces.id = workspace_memberships.workspace_id
            JOIN memberships ON memberships.id = workspace_memberships.membership_id
            WHERE workspaces.organization_id != memberships.organization_id
            """
            )
        )
        .scalar_one()
    )
    if conflict_count:
        raise RuntimeError(
            "Cannot apply tenant isolation migration with legacy cross-tenant workspace "
            f"memberships: found {conflict_count} workspace membership row(s) whose workspace "
            "and membership belong to different organizations."
        )
