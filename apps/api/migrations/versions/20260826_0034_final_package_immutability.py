"""Enforce final review package metadata immutability in PostgreSQL.

Revision ID: 20260826_0034
Revises: 20260825_0032
Create Date: 2026-08-26

The down revision is provisional while issue #210 owns 20260826_0033. Change
``down_revision`` to ``20260826_0033`` after that migration merges.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0034"
down_revision: str | None = "20260825_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("review_workflow_outbox", sa.Column("package_snapshot", sa.JSON(), nullable=True))
    op.add_column(
        "review_workflow_outbox",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "review_workflow_outbox",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_workflow_outbox", sa.Column("lease_owner", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "review_workflow_outbox",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_workflow_outbox", sa.Column("last_error", sa.String(length=512), nullable=True)
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE FUNCTION prevent_review_final_package_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'review final packages are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_terminal_package_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.event_type = 'review.workflow.terminal' THEN
              RAISE EXCEPTION 'terminal workflow outbox business fields are immutable';
            END IF;
            RETURN OLD;
          END IF;
          IF (OLD.event_type = 'review.workflow.terminal'
              OR NEW.event_type = 'review.workflow.terminal')
             AND (
               NEW.id IS DISTINCT FROM OLD.id
               OR NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
               OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.event_type IS DISTINCT FROM OLD.event_type
               OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
               OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
               OR NEW.package_snapshot::jsonb IS DISTINCT FROM OLD.package_snapshot::jsonb
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
             ) THEN
            RAISE EXCEPTION 'terminal workflow outbox business fields are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_workflow_terminal_snapshot_immutable
        BEFORE UPDATE OR DELETE ON review_workflow_outbox
        FOR EACH ROW EXECUTE FUNCTION prevent_terminal_package_snapshot_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_final_packages_immutable
        BEFORE UPDATE OR DELETE ON review_final_packages
        FOR EACH ROW EXECUTE FUNCTION prevent_review_final_package_mutation();
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS review_workflow_terminal_snapshot_immutable "
            "ON review_workflow_outbox"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_terminal_package_snapshot_mutation")
        op.execute(
            "DROP TRIGGER IF EXISTS review_final_packages_immutable ON review_final_packages"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_review_final_package_mutation")
    for column in (
        "last_error",
        "lease_expires_at",
        "lease_owner",
        "next_attempt_at",
        "attempt_count",
        "package_snapshot",
    ):
        op.drop_column("review_workflow_outbox", column)
