"""Allow draft playbook versions to be deleted.

Revision ID: 20260802_0015
Revises: 20260802_0014
Create Date: 2026-08-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260802_0015"
down_revision: str | None = "20260802_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_published_playbook_version_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'published' THEN
            RAISE EXCEPTION 'published playbook versions are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            RETURN OLD;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_published_playbook_version_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'published' THEN
            RAISE EXCEPTION 'published playbook versions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
