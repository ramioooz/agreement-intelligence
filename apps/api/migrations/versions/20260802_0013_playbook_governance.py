"""Add playbook routing scope and archive lifecycle.

Revision ID: 20260802_0013
Revises: 20260801_0012
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0013"
down_revision: str | None = "20260801_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("legal_playbooks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "document_direction", sa.String(length=32), nullable=False, server_default="any"
            )
        )
        batch_op.add_column(
            sa.Column("jurisdiction", sa.String(length=16), nullable=False, server_default="any")
        )
        batch_op.add_column(
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100")
        )
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_legal_playbooks_scope_routing",
        "legal_playbooks",
        [
            "organization_id",
            "workspace_id",
            "agreement_family",
            "document_direction",
            "jurisdiction",
            "priority",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_playbooks_scope_routing", table_name="legal_playbooks")
    with op.batch_alter_table("legal_playbooks") as batch_op:
        batch_op.drop_column("archived_at")
        batch_op.drop_column("priority")
        batch_op.drop_column("jurisdiction")
        batch_op.drop_column("document_direction")
