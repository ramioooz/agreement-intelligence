"""Persist immutable terminal review package metadata.

Revision ID: 20260805_0027
Revises: 20260805_0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0027"
down_revision: str | None = "20260805_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "review_final_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("manifest_key", sa.String(length=512), nullable=False),
        sa.Column("pdf_key", sa.String(length=512), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=128), nullable=False),
        sa.Column("pdf_checksum", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(["review_id"], ["review_cases.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["review_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", name="uq_review_final_packages_review"),
        sa.UniqueConstraint("manifest_key"),
        sa.UniqueConstraint("pdf_key"),
    )
    op.create_index(
        "ix_review_final_packages_scope_review",
        "review_final_packages",
        ["organization_id", "workspace_id", "review_id"],
    )


def downgrade() -> None:
    op.drop_table("review_final_packages")
