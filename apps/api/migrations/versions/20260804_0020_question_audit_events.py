"""Create immutable audit records for persistent Q&A activity.

Revision ID: 20260804_0020
Revises: 20260804_0019
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0020"
down_revision: str | None = "20260804_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "question_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_audit_events_scope_thread_occurred",
        "question_audit_events",
        ["organization_id", "workspace_id", "thread_id", "occurred_at"],
    )
    op.create_index("ix_question_audit_events_turn_id", "question_audit_events", ["turn_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE question_audit_events ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE question_audit_events FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation_question_audit_events
            ON question_audit_events
            USING (organization_id = current_setting('app.organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP POLICY IF EXISTS tenant_isolation_question_audit_events ON question_audit_events"
        )
        op.execute("ALTER TABLE question_audit_events DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_question_audit_events_turn_id", table_name="question_audit_events")
    op.drop_index(
        "ix_question_audit_events_scope_thread_occurred", table_name="question_audit_events"
    )
    op.drop_table("question_audit_events")
