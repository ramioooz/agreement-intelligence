"""Enforce final review package metadata immutability in PostgreSQL.

Revision ID: 20260826_0034
Revises: 20260825_0032
Create Date: 2026-08-26

The down revision is provisional while issue #210 owns 20260826_0033. Change
``down_revision`` to ``20260826_0033`` after that migration merges.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0034"
down_revision: str | None = "20260825_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
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
        CREATE TRIGGER review_final_packages_immutable
        BEFORE UPDATE OR DELETE ON review_final_packages
        FOR EACH ROW EXECUTE FUNCTION prevent_review_final_package_mutation();
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DROP TRIGGER IF EXISTS review_final_packages_immutable ON review_final_packages"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_review_final_package_mutation")
