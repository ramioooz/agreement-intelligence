"""Snapshot the immutable source selected for a processing job.

Revision ID: 20260801_0006
Revises: 20260731_0005
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0006"
down_revision: str | None = "20260731_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs", sa.Column("source_storage_key", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("source_checksum", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("source_content_type", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "source_content_type")
    op.drop_column("processing_jobs", "source_checksum")
    op.drop_column("processing_jobs", "source_storage_key")
