"""Persist versioned pgvector embeddings for canonical retrieval chunks.

Revision ID: 20260803_0018
Revises: 20260803_0017
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0018"
down_revision: str | None = "20260803_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


class PgVector(sa.types.UserDefinedType[object]):
    cache_ok = True

    def get_col_spec(self, **kwargs: object) -> str:
        del kwargs
        return "vector"


def upgrade() -> None:
    embedding_type: sa.types.TypeEngine[object] = sa.JSON()
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        embedding_type = PgVector()
    op.create_table(
        "retrieval_chunk_embeddings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("build_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.String(length=80), nullable=False),
        sa.Column("index_version", sa.String(length=100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("configuration_version", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("retry_outcome", sa.String(length=64), nullable=False),
        sa.Column("fallback_outcome", sa.String(length=64), nullable=False),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id", "build_id", "chunk_id"],
            [
                "retrieval_chunks.agreement_id",
                "retrieval_chunks.build_id",
                "retrieval_chunks.chunk_id",
            ],
            name="fk_retrieval_chunk_embeddings_chunk",
        ),
        sa.PrimaryKeyConstraint(
            "agreement_id",
            "build_id",
            "chunk_id",
            "index_version",
            "dimensions",
            name="pk_retrieval_chunk_embeddings",
        ),
    )
    op.create_index(
        "ix_retrieval_chunk_embeddings_scope_ready",
        "retrieval_chunk_embeddings",
        [
            "organization_id",
            "workspace_id",
            "agreement_id",
            "index_version",
            "dimensions",
            "state",
        ],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE retrieval_chunk_embeddings ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE retrieval_chunk_embeddings FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation_retrieval_chunk_embeddings
            ON retrieval_chunk_embeddings
            USING (organization_id = current_setting('app.organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
            """
        )
        op.execute(
            """
            CREATE TRIGGER retrieval_chunk_embeddings_organization_immutable
            BEFORE UPDATE ON retrieval_chunk_embeddings
            FOR EACH ROW EXECUTE FUNCTION prevent_organization_id_change();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS retrieval_chunk_embeddings_organization_immutable "
            "ON retrieval_chunk_embeddings"
        )
        op.execute(
            "DROP POLICY IF EXISTS tenant_isolation_retrieval_chunk_embeddings "
            "ON retrieval_chunk_embeddings"
        )
        op.execute("ALTER TABLE retrieval_chunk_embeddings DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_retrieval_chunk_embeddings_scope_ready",
        table_name="retrieval_chunk_embeddings",
    )
    op.drop_table("retrieval_chunk_embeddings")
