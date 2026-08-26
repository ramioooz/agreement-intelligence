"""Add durable, tenant-scoped agreement deletion requests and outbox.

Revision ID: 20260826_0033
Revises: 20260825_0032
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0033"
down_revision: str | None = "20260825_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agreements",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agreements_deletion_requested_at",
        "agreements",
        ["deletion_requested_at"],
    )
    op.add_column(
        "agreement_deletion_audit_events",
        sa.Column("deletion_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "agreement_deletion_audit_events",
        sa.Column(
            "event_type",
            sa.String(length=32),
            server_default="requested",
            nullable=False,
        ),
    )
    op.add_column(
        "agreement_deletion_audit_events",
        sa.Column("metadata_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.create_index(
        "ix_agreement_deletion_audit_events_deletion_id",
        "agreement_deletion_audit_events",
        ["deletion_id"],
    )
    op.create_table(
        "agreement_deletion_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("agreement_type", sa.String(length=100), nullable=False),
        sa.Column("file_checksums", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("object_keys", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agreement_id",
            name="uq_agreement_deletion_requests_agreement",
        ),
    )
    for column_name in (
        "organization_id",
        "workspace_id",
        "agreement_id",
        "actor_id",
        "state",
    ):
        op.create_index(
            f"ix_agreement_deletion_requests_{column_name}",
            "agreement_deletion_requests",
            [column_name],
        )
    op.create_index(
        "ix_agreement_deletion_requests_scope_state",
        "agreement_deletion_requests",
        ["organization_id", "workspace_id", "state"],
    )
    op.create_table(
        "agreement_deletion_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deletion_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["deletion_id"],
            ["agreement_deletion_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deletion_id",
            name="uq_agreement_deletion_outbox_deletion",
        ),
    )
    for column_name in ("deletion_id", "organization_id", "workspace_id", "agreement_id"):
        op.create_index(
            f"ix_agreement_deletion_outbox_{column_name}",
            "agreement_deletion_outbox",
            [column_name],
        )
    op.create_index(
        "ix_agreement_deletion_outbox_pending",
        "agreement_deletion_outbox",
        ["delivered_at", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        for table_name in ("agreement_deletion_requests", "agreement_deletion_outbox"):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_{table_name} ON {table_name}
                    FOR ALL
                    USING (
                        organization_id = current_setting('app.organization_id', true)::uuid
                    )
                    WITH CHECK (
                        organization_id = current_setting('app.organization_id', true)::uuid
                    )
                """
            )


def downgrade() -> None:
    op.drop_table("agreement_deletion_outbox")
    op.drop_table("agreement_deletion_requests")
    op.drop_index(
        "ix_agreement_deletion_audit_events_deletion_id",
        table_name="agreement_deletion_audit_events",
    )
    op.drop_column("agreement_deletion_audit_events", "metadata_json")
    op.drop_column("agreement_deletion_audit_events", "event_type")
    op.drop_column("agreement_deletion_audit_events", "deletion_id")
    op.drop_index("ix_agreements_deletion_requested_at", table_name="agreements")
    op.drop_column("agreements", "deletion_requested_at")
