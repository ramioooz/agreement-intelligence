"""Widen permission keys for approval-policy administration.

Revision ID: 20260806_0028
Revises: 20260805_0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0028"
down_revision: str | None = "20260805_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def _widen_permission_key() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("permissions") as batch_op:
            batch_op.alter_column(
                "key",
                existing_type=sa.String(length=17),
                type_=sa.String(length=64),
                existing_nullable=False,
            )
        return

    op.alter_column(
        "permissions",
        "key",
        existing_type=sa.String(length=17),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def upgrade() -> None:
    """Upgrade existing installations that already passed migration 0024."""
    _widen_permission_key()


def downgrade() -> None:
    """Restore the original width only when all keys fit within it."""
    op.alter_column(
        "permissions",
        "key",
        existing_type=sa.String(length=64),
        type_=sa.String(length=17),
        existing_nullable=False,
    )
