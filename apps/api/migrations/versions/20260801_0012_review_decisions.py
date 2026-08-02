"""Add immutable reviewer decision and review audit events.

Revision ID: 20260801_0012
Revises: 20260801_0011
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0012"
down_revision: str | None = "20260801_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("playbook_findings") as batch_op:
        batch_op.create_unique_constraint(
            "uq_playbook_findings_scope_id",
            ["organization_id", "workspace_id", "id"],
        )
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("original_result", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("edited_result", sa.String(length=32), nullable=True),
        sa.Column("edited_severity", sa.String(length=16), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('accepted', 'rejected', 'edited')",
            name="ck_review_decisions_action",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "finding_id"],
            [
                "playbook_findings.organization_id",
                "playbook_findings.workspace_id",
                "playbook_findings.id",
            ],
            name="fk_review_decisions_finding_scope",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_decisions_scope_finding",
        "review_decisions",
        ["organization_id", "workspace_id", "finding_id", "occurred_at"],
    )
    op.create_table(
        "review_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("agreement_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_audit_events_scope_occurred",
        "review_audit_events",
        ["organization_id", "workspace_id", "occurred_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_guards()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _disable_postgresql_guards()
    op.drop_index("ix_review_audit_events_scope_occurred", table_name="review_audit_events")
    op.drop_table("review_audit_events")
    op.drop_index("ix_review_decisions_scope_finding", table_name="review_decisions")
    op.drop_table("review_decisions")
    with op.batch_alter_table("playbook_findings") as batch_op:
        batch_op.drop_constraint("uq_playbook_findings_scope_id", type_="unique")


def _enable_postgresql_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_review_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'review events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table_name in ("review_decisions", "review_audit_events"):
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
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_review_event_mutation()
            """
        )


def _disable_postgresql_guards() -> None:
    for table_name in ("review_audit_events", "review_decisions"):
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_immutable ON {table_name}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS prevent_review_event_mutation")
