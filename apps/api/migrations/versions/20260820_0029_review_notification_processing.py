"""Track idempotent processing of review notification events.

Revision ID: 20260820_0029
Revises: 20260806_0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0029"
down_revision: str | None = "20260806_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "review_notification_events",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_notification_events", "processed_at")
