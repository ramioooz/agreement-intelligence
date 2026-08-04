"""Persist immutable version comparison runs and changes.

Revision ID: 20260804_0022
Revises: 20260804_0021
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0022"
down_revision: str | None = "20260804_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "version_comparison_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_version_id", sa.Uuid(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("analysis_version", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("analysis_provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreements.id"]),
        sa.ForeignKeyConstraint(["baseline_version_id"], ["agreement_versions.id"]),
        sa.ForeignKeyConstraint(["target_version_id"], ["agreement_versions.id"]),
        sa.ForeignKeyConstraint(["processing_job_id"], ["processing_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agreement_id",
            "baseline_version_id",
            "target_version_id",
            "analysis_version",
            name="uq_version_comparison_identity",
        ),
        sa.UniqueConstraint(
            "agreement_id", "idempotency_key", name="uq_version_comparison_idempotency"
        ),
    )
    op.create_index(
        "ix_version_comparison_runs_organization_id", "version_comparison_runs", ["organization_id"]
    )
    op.create_index(
        "ix_version_comparison_runs_workspace_id", "version_comparison_runs", ["workspace_id"]
    )
    op.create_index(
        "ix_version_comparison_runs_agreement_id", "version_comparison_runs", ["agreement_id"]
    )
    op.create_index(
        "ix_version_comparison_runs_baseline_version_id",
        "version_comparison_runs",
        ["baseline_version_id"],
    )
    op.create_index(
        "ix_version_comparison_runs_target_version_id",
        "version_comparison_runs",
        ["target_version_id"],
    )
    op.create_index("ix_version_comparison_runs_state", "version_comparison_runs", ["state"])
    op.create_index(
        "ix_version_comparison_scope_state",
        "version_comparison_runs",
        ["organization_id", "workspace_id", "state"],
    )
    op.create_table(
        "version_comparison_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("comparison_run_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("alignment_kind", sa.String(length=32), nullable=False),
        sa.Column("baseline_element_ids", sa.JSON(), nullable=False),
        sa.Column("target_element_ids", sa.JSON(), nullable=False),
        sa.Column("baseline_citation_ids", sa.JSON(), nullable=False),
        sa.Column("target_citation_ids", sa.JSON(), nullable=False),
        sa.Column("word_diff", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("legal_concepts", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("provider_provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["comparison_run_id"], ["version_comparison_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_run_id", "ordinal", name="uq_version_comparison_change_ordinal"
        ),
    )
    for column in ("comparison_run_id", "organization_id", "workspace_id", "agreement_id"):
        op.create_index(
            f"ix_version_comparison_changes_{column}", "version_comparison_changes", [column]
        )
    op.create_index(
        "ix_version_comparison_changes_run",
        "version_comparison_changes",
        ["comparison_run_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_table("version_comparison_changes")
    op.drop_table("version_comparison_runs")
