"""Add versioned legal playbooks and immutable policy audit events.

Revision ID: 20260801_0008
Revises: 20260801_0007
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0008"
down_revision: str | None = "20260801_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_playbooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("agreement_family", sa.String(length=100), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_legal_playbooks_scope_id"
        ),
    )
    op.create_index(
        "ix_legal_playbooks_scope_family",
        "legal_playbooks",
        ["organization_id", "workspace_id", "agreement_family"],
    )
    op.create_table(
        "playbook_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("playbook_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id", "playbook_id"],
            [
                "legal_playbooks.organization_id",
                "legal_playbooks.workspace_id",
                "legal_playbooks.id",
            ],
            name="fk_playbook_versions_scope_playbook",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "workspace_id", "id", name="uq_playbook_versions_scope_id"
        ),
        sa.UniqueConstraint("playbook_id", "version", name="uq_playbook_versions_playbook_version"),
    )
    op.create_index(
        "ix_playbook_versions_scope_status",
        "playbook_versions",
        ["organization_id", "workspace_id", "status"],
    )
    op.create_index(
        "uq_playbook_versions_one_published",
        "playbook_versions",
        ["playbook_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "playbook_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("playbook_version_id", sa.Uuid(), nullable=False),
        sa.Column("clause_type", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("policy_type", sa.String(length=16), nullable=False),
        sa.Column("preferred_language", sa.String(), nullable=True),
        sa.Column("fallback_language", sa.String(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("legal_rationale", sa.String(), nullable=False),
        sa.Column("reviewer_guidance", sa.String(), nullable=False),
        sa.Column("evaluation_config", sa.JSON(), nullable=False),
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
            ["organization_id", "workspace_id", "playbook_version_id"],
            [
                "playbook_versions.organization_id",
                "playbook_versions.workspace_id",
                "playbook_versions.id",
            ],
            name="fk_playbook_rules_scope_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "playbook_version_id", "clause_type", name="uq_playbook_rules_version_clause_type"
        ),
    )
    op.create_index(
        "ix_playbook_rules_scope_version",
        "playbook_rules",
        ["organization_id", "workspace_id", "playbook_version_id"],
    )
    op.create_table(
        "playbook_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("playbook_id", sa.Uuid(), nullable=False),
        sa.Column("playbook_version_id", sa.Uuid(), nullable=True),
        sa.Column("playbook_rule_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["organization_id", "workspace_id"],
            ["workspaces.organization_id", "workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_playbook_audit_events_scope_version",
        "playbook_audit_events",
        ["organization_id", "workspace_id", "playbook_version_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_tenant_isolation()
        _create_immutable_triggers()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _drop_immutable_triggers()
        _disable_postgresql_tenant_isolation()
    op.drop_index("ix_playbook_audit_events_scope_version", table_name="playbook_audit_events")
    op.drop_table("playbook_audit_events")
    op.drop_index("ix_playbook_rules_scope_version", table_name="playbook_rules")
    op.drop_table("playbook_rules")
    op.drop_index("uq_playbook_versions_one_published", table_name="playbook_versions")
    op.drop_index("ix_playbook_versions_scope_status", table_name="playbook_versions")
    op.drop_table("playbook_versions")
    op.drop_index("ix_legal_playbooks_scope_family", table_name="legal_playbooks")
    op.drop_table("legal_playbooks")


def _create_immutable_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_published_playbook_version_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'published' THEN
            RAISE EXCEPTION 'published playbook versions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER playbook_version_published_immutable
        BEFORE UPDATE OR DELETE ON playbook_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_published_playbook_version_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_published_playbook_rule_mutation() RETURNS trigger AS $$
        DECLARE version_id uuid;
        BEGIN
          version_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.playbook_version_id
                             ELSE NEW.playbook_version_id END;
          IF EXISTS (
            SELECT 1 FROM playbook_versions WHERE id = version_id AND status = 'published'
          ) THEN
            RAISE EXCEPTION 'published playbook rules are immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER playbook_rule_published_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON playbook_rules
        FOR EACH ROW EXECUTE FUNCTION prevent_published_playbook_rule_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_playbook_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'playbook audit events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER playbook_audit_immutable
        BEFORE UPDATE OR DELETE ON playbook_audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_playbook_audit_mutation();
        """
    )


def _enable_postgresql_tenant_isolation() -> None:
    for table_name in (
        "legal_playbooks",
        "playbook_versions",
        "playbook_rules",
        "playbook_audit_events",
    ):
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


def _disable_postgresql_tenant_isolation() -> None:
    for table_name in (
        "playbook_audit_events",
        "playbook_rules",
        "playbook_versions",
        "legal_playbooks",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_organization_immutable ON {table_name}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def _drop_immutable_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS playbook_audit_immutable ON playbook_audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_playbook_audit_mutation")
    op.execute("DROP TRIGGER IF EXISTS playbook_rule_published_immutable ON playbook_rules")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_playbook_rule_mutation")
    op.execute("DROP TRIGGER IF EXISTS playbook_version_published_immutable ON playbook_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_playbook_version_mutation")
