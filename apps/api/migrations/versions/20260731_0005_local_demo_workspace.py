"""Seed the deterministic local agreement-repository workspace.

Revision ID: 20260731_0005
Revises: 20260731_0004
Create Date: 2026-07-31
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0005"
down_revision: str | None = "20260731_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEMO_ORGANIZATION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DEMO_WORKSPACE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

organizations = sa.table(
    "organizations",
    sa.column("id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("slug", sa.String()),
)
workspaces = sa.table(
    "workspaces",
    sa.column("id", sa.Uuid()),
    sa.column("organization_id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("slug", sa.String()),
)


def upgrade() -> None:
    op.bulk_insert(
        organizations, [{"id": DEMO_ORGANIZATION_ID, "name": "Demo Legal", "slug": "demo-legal"}]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text("SELECT set_config('app.organization_id', :organization_id, true)").bindparams(
                organization_id=str(DEMO_ORGANIZATION_ID)
            )
        )
    op.bulk_insert(
        workspaces,
        [
            {
                "id": DEMO_WORKSPACE_ID,
                "organization_id": DEMO_ORGANIZATION_ID,
                "name": "Agreement Repository",
                "slug": "agreement-repository",
            }
        ],
    )


def downgrade() -> None:
    op.execute(workspaces.delete().where(workspaces.c.id == DEMO_WORKSPACE_ID))
    op.execute(organizations.delete().where(organizations.c.id == DEMO_ORGANIZATION_ID))
