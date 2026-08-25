"""Add the tenant-scoped AI usage reservation ledger.

Revision ID: 20260825_0032
Revises: 20260825_0031
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0032"
down_revision: str | None = "20260825_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_ledger",
        sa.Column("reservation_id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("configuration_version", sa.String(length=128), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_usd", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("settlement_key", sa.String(length=255), nullable=True, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_usage_ledger_organization_id", "ai_usage_ledger", ["organization_id"])
    op.create_index("ix_ai_usage_ledger_workspace_id", "ai_usage_ledger", ["workspace_id"])
    op.create_index("ix_ai_usage_ledger_user_id", "ai_usage_ledger", ["user_id"])
    op.create_index("ix_ai_usage_ledger_status", "ai_usage_ledger", ["status"])
    op.create_index(
        "ix_ai_usage_ledger_scope_created",
        "ai_usage_ledger",
        ["organization_id", "workspace_id", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE ai_usage_ledger ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE ai_usage_ledger FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation_ai_usage_ledger ON ai_usage_ledger
            FOR ALL
            USING (organization_id = current_setting('app.organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
            """
        )


def downgrade() -> None:
    op.drop_table("ai_usage_ledger")
