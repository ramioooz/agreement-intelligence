"""Create agreement repository tables.

Revision ID: 20260731_0002
Revises: 20260731_0001
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agreements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("agreement_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parties", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("processing_state", sa.String(length=32), nullable=False),
        sa.Column("audit_metadata", sa.JSON(), nullable=False),
        sa.Column("audit_events", sa.JSON(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agreements_agreement_type", "agreements", ["agreement_type"])
    op.create_index("ix_agreements_organization_id", "agreements", ["organization_id"])
    op.create_index(
        "ix_agreements_scope_created",
        "agreements",
        ["organization_id", "workspace_id", "created_at"],
    )
    op.create_index("ix_agreements_status", "agreements", ["status"])
    op.create_index("ix_agreements_workspace_id", "agreements", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_agreements_workspace_id", table_name="agreements")
    op.drop_index("ix_agreements_status", table_name="agreements")
    op.drop_index("ix_agreements_scope_created", table_name="agreements")
    op.drop_index("ix_agreements_organization_id", table_name="agreements")
    op.drop_index("ix_agreements_agreement_type", table_name="agreements")
    op.drop_table("agreements")
