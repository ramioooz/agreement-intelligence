"""Add immutable agreement deletion audit events.

Revision ID: 20260801_0007
Revises: 20260801_0006
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0007"
down_revision: str | None = "20260801_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agreement_deletion_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("agreement_type", sa.String(length=100), nullable=False),
        sa.Column("file_checksums", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agreement_deletion_audit_events_agreement_id",
        "agreement_deletion_audit_events",
        ["agreement_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_agreement_deletion_audit_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'agreement deletion audit events are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER agreement_deletion_audit_immutable
            BEFORE UPDATE OR DELETE ON agreement_deletion_audit_events
            FOR EACH ROW EXECUTE FUNCTION prevent_agreement_deletion_audit_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS agreement_deletion_audit_immutable "
            "ON agreement_deletion_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_agreement_deletion_audit_mutation")
    op.drop_index(
        "ix_agreement_deletion_audit_events_agreement_id",
        table_name="agreement_deletion_audit_events",
    )
    op.drop_table("agreement_deletion_audit_events")
