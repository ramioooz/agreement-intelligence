"""Add immutable MCP tool audit events.

Revision ID: 20260802_0016
Revises: 20260802_0015
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0016"
down_revision: str | None = "20260802_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_audit_events_scope_occurred",
        "mcp_audit_events",
        ["organization_id", "workspace_id", "occurred_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_mcp_audit_event_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'MCP audit events are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER mcp_audit_events_immutable
            BEFORE UPDATE OR DELETE ON mcp_audit_events
            FOR EACH ROW EXECUTE FUNCTION prevent_mcp_audit_event_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS mcp_audit_events_immutable ON mcp_audit_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_mcp_audit_event_mutation")
    op.drop_index("ix_mcp_audit_events_scope_occurred", table_name="mcp_audit_events")
    op.drop_table("mcp_audit_events")
