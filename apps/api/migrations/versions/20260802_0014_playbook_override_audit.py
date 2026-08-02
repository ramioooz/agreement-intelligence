"""Add agreement references to immutable playbook audit events.

Revision ID: 20260802_0014
Revises: 20260802_0013
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0014"
down_revision: str | None = "20260802_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("playbook_audit_events") as batch_op:
        batch_op.add_column(sa.Column("agreement_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_playbook_audit_events_scope_agreement",
        "playbook_audit_events",
        ["organization_id", "workspace_id", "agreement_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_playbook_audit_events_scope_agreement", table_name="playbook_audit_events")
    with op.batch_alter_table("playbook_audit_events") as batch_op:
        batch_op.drop_column("agreement_id")
