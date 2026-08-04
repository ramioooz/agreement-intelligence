"""Create immutable agreement version lineage.

Revision ID: 20260804_0021
Revises: 20260804_0020
Create Date: 2026-08-04
"""

from collections.abc import Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0021"
down_revision: str | None = "20260804_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "agreement_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("predecessor_version_id", sa.Uuid(), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processing_state", sa.String(length=32), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=True),
        sa.Column("extraction_version", sa.String(length=100), nullable=True),
        sa.Column("analysis_provenance", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["agreement_id", "organization_id", "workspace_id"],
            ["agreements.id", "agreements.organization_id", "agreements.workspace_id"],
        ),
        sa.ForeignKeyConstraint(["predecessor_version_id"], ["agreement_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agreement_id", "version_number", name="uq_agreement_version_number"),
        sa.UniqueConstraint("agreement_id", "checksum", name="uq_agreement_version_checksum"),
        sa.UniqueConstraint(
            "agreement_id", "idempotency_key", name="uq_agreement_version_idempotency"
        ),
    )
    op.create_index("ix_agreement_versions_agreement_id", "agreement_versions", ["agreement_id"])
    op.create_index(
        "ix_agreement_versions_organization_id", "agreement_versions", ["organization_id"]
    )
    op.create_index("ix_agreement_versions_workspace_id", "agreement_versions", ["workspace_id"])
    op.create_index("ix_agreement_versions_uploaded_by", "agreement_versions", ["uploaded_by"])
    op.create_index(
        "ix_agreement_versions_processing_state", "agreement_versions", ["processing_state"]
    )
    op.create_index(
        "ix_agreement_versions_scope_lineage",
        "agreement_versions",
        ["organization_id", "workspace_id", "agreement_id", "version_number"],
    )
    op.create_table(
        "agreement_version_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "organization_id",
        "workspace_id",
        "agreement_id",
        "version_id",
        "actor_id",
    ):
        op.create_index(
            f"ix_agreement_version_audit_events_{column}",
            "agreement_version_audit_events",
            [column],
        )
    op.create_index(
        "ix_agreement_version_audit_scope_version",
        "agreement_version_audit_events",
        ["organization_id", "workspace_id", "version_id", "occurred_at"],
    )
    with op.batch_alter_table("agreements") as batch_op:
        batch_op.add_column(sa.Column("current_version_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("comparison_baseline_version_id", sa.Uuid(), nullable=True))
    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.add_column(sa.Column("version_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_processing_jobs_version_id", "agreement_versions", ["version_id"], ["id"]
        )
        batch_op.create_index("ix_processing_jobs_version_id", ["version_id"])

    _backfill_existing_agreements()

    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_controls()


def _backfill_existing_agreements() -> None:
    connection = op.get_bind()
    agreements = connection.execute(
        sa.text(
            "SELECT id, organization_id, workspace_id, files, processing_state, "
            "audit_events, created_at FROM agreements"
        )
    ).mappings()
    for agreement in agreements:
        files = agreement["files"] or []
        if not isinstance(files, list) or not files:
            continue
        source = files[-1]
        if not isinstance(source, dict):
            continue
        version_id = uuid4()
        actor_id = _created_actor_id(agreement["audit_events"], agreement["id"])
        connection.execute(
            sa.text(
                """
                INSERT INTO agreement_versions (
                    id, agreement_id, organization_id, workspace_id, version_number,
                    predecessor_version_id, file_name, content_type, storage_key, checksum,
                    byte_size, uploaded_by, uploaded_at, processing_state, processing_job_id,
                    extraction_version, analysis_provenance, idempotency_key
                ) VALUES (
                    :id, :agreement_id, :organization_id, :workspace_id, 1,
                    NULL, :file_name, :content_type, :storage_key, :checksum,
                    :byte_size, :uploaded_by, :uploaded_at, :processing_state, NULL,
                    NULL, :analysis_provenance, :idempotency_key
                )
                """
            ),
            {
                "id": version_id,
                "agreement_id": agreement["id"],
                "organization_id": agreement["organization_id"],
                "workspace_id": agreement["workspace_id"],
                "file_name": str(source.get("file_name", "source")),
                "content_type": str(source.get("content_type", "application/octet-stream")),
                "storage_key": str(source.get("storage_key", "legacy-source")),
                "checksum": str(source.get("checksum", f"legacy:{agreement['id']}")),
                "byte_size": int(source.get("byte_size", 0)),
                "uploaded_by": actor_id,
                "uploaded_at": agreement["created_at"],
                "processing_state": agreement["processing_state"],
                "analysis_provenance": {},
                "idempotency_key": f"migration:{agreement['id']}",
            },
        )
        connection.execute(
            sa.text("UPDATE agreements SET current_version_id = :version_id WHERE id = :id"),
            {"version_id": version_id, "id": agreement["id"]},
        )


def _created_actor_id(events: object, fallback: object) -> UUID:
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and event.get("action") == "created":
                try:
                    return UUID(str(event.get("actor_id")))
                except (TypeError, ValueError):
                    break
    try:
        return UUID(str(fallback))
    except (TypeError, ValueError):
        return uuid4()


def _enable_postgresql_controls() -> None:
    for table in ("agreement_versions", "agreement_version_audit_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (organization_id = current_setting('app.organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
            """
        )
    op.execute(
        """
        CREATE FUNCTION prevent_agreement_version_source_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.agreement_id IS DISTINCT FROM NEW.agreement_id
             OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
             OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
             OR OLD.version_number IS DISTINCT FROM NEW.version_number
             OR OLD.predecessor_version_id IS DISTINCT FROM NEW.predecessor_version_id
             OR OLD.file_name IS DISTINCT FROM NEW.file_name
             OR OLD.content_type IS DISTINCT FROM NEW.content_type
             OR OLD.storage_key IS DISTINCT FROM NEW.storage_key
             OR OLD.checksum IS DISTINCT FROM NEW.checksum
             OR OLD.byte_size IS DISTINCT FROM NEW.byte_size
             OR OLD.uploaded_by IS DISTINCT FROM NEW.uploaded_by
             OR OLD.uploaded_at IS DISTINCT FROM NEW.uploaded_at
             OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key THEN
            RAISE EXCEPTION 'Agreement version source lineage is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER agreement_version_source_immutable
        BEFORE UPDATE ON agreement_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_agreement_version_source_mutation();
        CREATE FUNCTION prevent_agreement_version_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'Agreement version audit events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER agreement_version_audit_immutable
        BEFORE UPDATE OR DELETE ON agreement_version_audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_agreement_version_audit_mutation();
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS agreement_version_audit_immutable "
            "ON agreement_version_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_agreement_version_audit_mutation")
        op.execute(
            "DROP TRIGGER IF EXISTS agreement_version_source_immutable ON agreement_versions"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_agreement_version_source_mutation")
        for table in ("agreement_version_audit_events", "agreement_versions"):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.drop_index("ix_processing_jobs_version_id")
        batch_op.drop_constraint("fk_processing_jobs_version_id", type_="foreignkey")
        batch_op.drop_column("version_id")
    with op.batch_alter_table("agreements") as batch_op:
        batch_op.drop_column("comparison_baseline_version_id")
        batch_op.drop_column("current_version_id")
    op.drop_index(
        "ix_agreement_version_audit_scope_version",
        table_name="agreement_version_audit_events",
    )
    for column in (
        "actor_id",
        "version_id",
        "agreement_id",
        "workspace_id",
        "organization_id",
    ):
        op.drop_index(
            f"ix_agreement_version_audit_events_{column}",
            table_name="agreement_version_audit_events",
        )
    op.drop_table("agreement_version_audit_events")
    op.drop_index("ix_agreement_versions_scope_lineage", table_name="agreement_versions")
    op.drop_index("ix_agreement_versions_processing_state", table_name="agreement_versions")
    op.drop_index("ix_agreement_versions_uploaded_by", table_name="agreement_versions")
    op.drop_index("ix_agreement_versions_workspace_id", table_name="agreement_versions")
    op.drop_index("ix_agreement_versions_organization_id", table_name="agreement_versions")
    op.drop_index("ix_agreement_versions_agreement_id", table_name="agreement_versions")
    op.drop_table("agreement_versions")
