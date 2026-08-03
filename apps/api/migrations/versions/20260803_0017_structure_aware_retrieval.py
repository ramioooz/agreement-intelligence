"""Add tenant-isolated canonical retrieval index tables.

Revision ID: 20260803_0017
Revises: 20260802_0016
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0017"
down_revision: str | None = "20260802_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("agreements") as batch_op:
        batch_op.create_unique_constraint(
            "uq_agreements_scope",
            ["id", "organization_id", "workspace_id"],
        )

    op.create_table(
        "retrieval_index_builds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("source_checksum", sa.String(length=255), nullable=False),
        sa.Column("chunker_version", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            [
                "agreements.id",
                "agreements.organization_id",
                "agreements.workspace_id",
            ],
            name="fk_retrieval_index_builds_agreement_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agreement_id",
            "source_checksum",
            "chunker_version",
            name="uq_retrieval_index_build_source",
        ),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            "workspace_id",
            "agreement_id",
            name="uq_retrieval_index_build_scope",
        ),
    )
    op.create_index(
        "ix_retrieval_index_builds_scope_active",
        "retrieval_index_builds",
        ["organization_id", "workspace_id", "agreement_id", "state"],
    )
    op.create_index(
        "uq_retrieval_index_builds_active_scope",
        "retrieval_index_builds",
        ["organization_id", "workspace_id", "agreement_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "retrieval_chunks",
        sa.Column("chunk_id", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("build_id", sa.Uuid(), nullable=False),
        sa.Column("source_checksum", sa.String(length=255), nullable=False),
        sa.Column("chunker_version", sa.String(length=100), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("anchor_ids", sa.JSON(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(["agreement_id"], ["agreements.id"]),
        sa.ForeignKeyConstraint(["build_id"], ["retrieval_index_builds.id"]),
        sa.PrimaryKeyConstraint("agreement_id", "build_id", "chunk_id", name="pk_retrieval_chunks"),
        sa.ForeignKeyConstraint(
            ["build_id", "organization_id", "workspace_id", "agreement_id"],
            [
                "retrieval_index_builds.id",
                "retrieval_index_builds.organization_id",
                "retrieval_index_builds.workspace_id",
                "retrieval_index_builds.agreement_id",
            ],
            name="fk_retrieval_chunks_build_scope",
        ),
    )
    op.create_index(
        "ix_retrieval_chunks_scope_build",
        "retrieval_chunks",
        ["organization_id", "workspace_id", "agreement_id", "build_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        for table_name in ("retrieval_index_builds", "retrieval_chunks"):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_{table_name} ON {table_name}
                USING (organization_id = current_setting('app.organization_id', true)::uuid)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table_name}_organization_immutable
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION prevent_organization_id_change();
                """
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table_name in ("retrieval_chunks", "retrieval_index_builds"):
            op.execute(
                f"DROP TRIGGER IF EXISTS {table_name}_organization_immutable ON {table_name}"
            )
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_retrieval_chunks_scope_build", table_name="retrieval_chunks")
    op.drop_table("retrieval_chunks")
    op.drop_index("uq_retrieval_index_builds_active_scope", table_name="retrieval_index_builds")
    op.drop_index("ix_retrieval_index_builds_scope_active", table_name="retrieval_index_builds")
    op.drop_table("retrieval_index_builds")
    with op.batch_alter_table("agreements") as batch_op:
        batch_op.drop_constraint("uq_agreements_scope", type_="unique")
