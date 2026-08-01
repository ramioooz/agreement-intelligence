"""Persist policy-bounded risk payloads for playbook findings.

Revision ID: 20260801_0010
Revises: 20260801_0009
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0010"
down_revision: str | None = "20260801_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "playbook_findings",
        sa.Column("risk_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("playbook_findings", "risk_payload")
