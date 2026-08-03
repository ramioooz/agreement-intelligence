"""Persist tenant-scoped grounded question threads and turns.

Revision ID: 20260804_0019
Revises: 20260803_0018
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0019"
down_revision: str | None = "20260803_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "question_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_ids", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "organization_id", "workspace_id", name="uq_question_threads_scope"
        ),
    )
    op.create_index(
        "ix_question_threads_scope_created",
        "question_threads",
        ["organization_id", "workspace_id", "created_at"],
    )
    op.create_table(
        "question_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(length=1000), nullable=False),
        sa.Column("answer_status", sa.String(length=32), nullable=False),
        sa.Column("answer_message", sa.String(), nullable=False),
        sa.Column("claims", sa.JSON(), nullable=False),
        sa.Column("retrieval_provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["thread_id", "organization_id", "workspace_id"],
            [
                "question_threads.id",
                "question_threads.organization_id",
                "question_threads.workspace_id",
            ],
            name="fk_question_turns_thread_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_turns_scope_thread_created",
        "question_turns",
        ["organization_id", "workspace_id", "thread_id", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in ("question_threads", "question_turns"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_{table}
                ON {table}
                USING (organization_id = current_setting('app.organization_id', true)::uuid)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
                """
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("question_turns", "question_threads"):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_question_turns_scope_thread_created", table_name="question_turns")
    op.drop_table("question_turns")
    op.drop_index("ix_question_threads_scope_created", table_name="question_threads")
    op.drop_table("question_threads")
