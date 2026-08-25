"""Add immutable AI configuration versions and promotions.

Revision ID: 20260825_0031
Revises: 20260824_0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0031"
down_revision: str | None = "20260824_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_configuration_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("prompt_checksum", sa.String(length=64), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("schema_checksum", sa.String(length=64), nullable=False),
        sa.Column("model_route", sa.String(length=256), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_ai_configuration_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "id",
            name="uq_ai_configuration_scope_id",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "workspace_id",
            "operation",
            "version",
            name="uq_ai_configuration_scope_operation_version",
        ),
    )
    op.create_index(
        "ix_ai_configuration_operation_status",
        "ai_configuration_versions",
        ["operation", "status"],
    )
    op.create_table(
        "ai_configuration_promotions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("promoted_by", sa.Uuid(), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "configuration_id"],
            [
                "ai_configuration_versions.organization_id",
                "ai_configuration_versions.workspace_id",
                "ai_configuration_versions.id",
            ],
        ),
        sa.ForeignKeyConstraint(["promoted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_configuration_promotions_lookup",
        "ai_configuration_promotions",
        ["organization_id", "workspace_id", "operation", "environment", "promoted_at"],
    )
    op.create_table(
        "ai_configuration_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "configuration_id"],
            [
                "ai_configuration_versions.organization_id",
                "ai_configuration_versions.workspace_id",
                "ai_configuration_versions.id",
            ],
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_configuration_audit_configuration",
        "ai_configuration_audit_events",
        ["configuration_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_published_ai_configuration_mutation() RETURNS trigger AS $$
            BEGIN
                IF OLD.status = 'published' THEN
                    RAISE EXCEPTION 'published AI configurations are immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table_name in (
            "ai_configuration_versions",
            "ai_configuration_promotions",
            "ai_configuration_audit_events",
        ):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation_{table_name} ON {table_name}
                    FOR ALL
                    USING (organization_id = current_setting('app.organization_id', true)::uuid)
                    WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
                """
            )
        op.execute(
            """
            CREATE TRIGGER ai_configuration_versions_immutable
            BEFORE UPDATE OR DELETE ON ai_configuration_versions
            FOR EACH ROW EXECUTE FUNCTION reject_published_ai_configuration_mutation();
            """
        )
        op.execute(
            """
            CREATE FUNCTION reject_ai_configuration_promotion_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'AI configuration promotions are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER ai_configuration_promotions_immutable
            BEFORE UPDATE OR DELETE ON ai_configuration_promotions
            FOR EACH ROW EXECUTE FUNCTION reject_ai_configuration_promotion_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table_name in (
            "ai_configuration_audit_events",
            "ai_configuration_promotions",
            "ai_configuration_versions",
        ):
            op.execute(f"DROP POLICY tenant_isolation_{table_name} ON {table_name}")
            op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
        op.execute(
            "DROP TRIGGER ai_configuration_promotions_immutable ON ai_configuration_promotions"
        )
        op.execute("DROP FUNCTION reject_ai_configuration_promotion_mutation")
        op.execute("DROP TRIGGER ai_configuration_versions_immutable ON ai_configuration_versions")
        op.execute("DROP FUNCTION reject_published_ai_configuration_mutation")
    op.drop_index(
        "ix_ai_configuration_audit_configuration",
        table_name="ai_configuration_audit_events",
    )
    op.drop_table("ai_configuration_audit_events")
    op.drop_index("ix_ai_configuration_promotions_lookup", table_name="ai_configuration_promotions")
    op.drop_table("ai_configuration_promotions")
    op.drop_index("ix_ai_configuration_operation_status", table_name="ai_configuration_versions")
    op.drop_table("ai_configuration_versions")
