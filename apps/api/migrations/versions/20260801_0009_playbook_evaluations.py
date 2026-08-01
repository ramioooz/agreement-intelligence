"""Add scoped, provenance-preserving playbook evaluations and findings.

Revision ID: 20260801_0009
Revises: 20260801_0008
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0009"
down_revision: str | None = "20260801_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "playbook_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("playbook_version_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_version", sa.String(length=100), nullable=False),
        sa.Column("extraction_version", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreements.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(["playbook_version_id"], ["playbook_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_playbook_evaluations_scope_agreement",
        "playbook_evaluations",
        ["organization_id", "workspace_id", "agreement_id"],
    )
    op.create_table(
        "playbook_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("extraction_version", sa.String(length=100), nullable=False),
        sa.Column("review_state", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id"], ["playbook_evaluations.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_playbook_findings_scope_evaluation",
        "playbook_findings",
        ["organization_id", "workspace_id", "evaluation_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_tenant_isolation()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _disable_postgresql_tenant_isolation()
    op.drop_index("ix_playbook_findings_scope_evaluation", table_name="playbook_findings")
    op.drop_table("playbook_findings")
    op.drop_index("ix_playbook_evaluations_scope_agreement", table_name="playbook_evaluations")
    op.drop_table("playbook_evaluations")


def _enable_postgresql_tenant_isolation() -> None:
    for table_name in ("playbook_evaluations", "playbook_findings"):
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table_name} ON {table_name}
            USING (organization_id = current_setting('app.organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_organization_immutable
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_organization_id_change();
            """
        )


def _disable_postgresql_tenant_isolation() -> None:
    for table_name in ("playbook_findings", "playbook_evaluations"):
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_organization_immutable ON {table_name}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
