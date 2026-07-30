"""Create durable agreement processing jobs.

Revision ID: 20260731_0004
Revises: 20260731_0003
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0004"
down_revision: str | None = "20260731_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("profile", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreements.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agreement_id", "idempotency_key", name="uq_processing_job_idempotency"
        ),
    )
    op.create_index("ix_processing_jobs_agreement_id", "processing_jobs", ["agreement_id"])
    op.create_index(
        "ix_processing_jobs_agreement_state", "processing_jobs", ["agreement_id", "state"]
    )
    op.create_index("ix_processing_jobs_organization_id", "processing_jobs", ["organization_id"])
    op.create_index("ix_processing_jobs_state", "processing_jobs", ["state"])
    op.create_index("ix_processing_jobs_workspace_id", "processing_jobs", ["workspace_id"])
    op.create_table(
        "processing_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_key", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreements.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_job_key"),
    )
    op.create_index(
        "ix_processing_artifacts_agreement_id", "processing_artifacts", ["agreement_id"]
    )
    op.create_index("ix_processing_artifacts_job_id", "processing_artifacts", ["job_id"])
    op.create_table(
        "processing_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("profile", sa.String(length=100), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreements.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_outbox_agreement_id", "processing_outbox", ["agreement_id"])
    op.create_index("ix_processing_outbox_job_id", "processing_outbox", ["job_id"])
    op.create_index(
        "ix_processing_outbox_pending", "processing_outbox", ["delivered_at", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_processing_outbox_pending", table_name="processing_outbox")
    op.drop_index("ix_processing_outbox_job_id", table_name="processing_outbox")
    op.drop_index("ix_processing_outbox_agreement_id", table_name="processing_outbox")
    op.drop_table("processing_outbox")
    op.drop_index("ix_processing_artifacts_job_id", table_name="processing_artifacts")
    op.drop_index("ix_processing_artifacts_agreement_id", table_name="processing_artifacts")
    op.drop_table("processing_artifacts")
    op.drop_index("ix_processing_jobs_workspace_id", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_state", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_organization_id", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_agreement_state", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_agreement_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")
