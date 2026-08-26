"""Persist expected processing artifact keys before object storage mutation.

Revision ID: 20260826_0034
Revises: 20260826_0033
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0034"
down_revision: str | None = "20260826_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_artifact_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("profile", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("artifact_key", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="expected", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "category IN ('analysis', 'comparison')",
            name="ck_processing_artifact_intents_category",
        ),
        sa.CheckConstraint(
            "state IN ('expected', 'settled')",
            name="ck_processing_artifact_intents_state",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            ["agreements.id", "agreements.organization_id", "agreements.workspace_id"],
            name="fk_processing_artifact_intents_agreement_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_processing_artifact_intents_job"),
        sa.UniqueConstraint("job_id", "artifact_key", name="uq_processing_artifact_intent_job_key"),
    )
    for column_name in ("job_id", "organization_id", "workspace_id", "agreement_id"):
        op.create_index(
            f"ix_processing_artifact_intents_{column_name}",
            "processing_artifact_intents",
            [column_name],
        )
    op.create_index(
        "ix_processing_artifact_intents_scope_agreement",
        "processing_artifact_intents",
        ["organization_id", "workspace_id", "agreement_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE processing_artifact_intents ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE processing_artifact_intents FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation_processing_artifact_intents
            ON processing_artifact_intents
            USING (
                organization_id = current_setting('app.organization_id', true)::uuid
            )
            WITH CHECK (
                organization_id = current_setting('app.organization_id', true)::uuid
            )
            """
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # The non-superuser migration owner has no tenant context. Temporarily
        # bypass FORCE RLS for this global safety check; a refusal rolls the DDL
        # back in the same transaction and restores FORCE automatically.
        op.execute("ALTER TABLE processing_artifact_intents NO FORCE ROW LEVEL SECURITY")
    if connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM processing_artifact_intents)")
    ).scalar():
        raise RuntimeError("cannot downgrade while processing artifact intents are pending")
    op.drop_table("processing_artifact_intents")
