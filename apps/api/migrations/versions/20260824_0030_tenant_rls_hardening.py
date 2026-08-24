"""Enforce row-level tenant isolation for every tenant-owned table.

Revision ID: 20260824_0030
Revises: 20260820_0029
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0030"
down_revision: str | None = "20260820_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None

# Every table with an organization_id is tenant-scoped.  The two processing
# children receive explicit scope columns below so their database boundary is
# independent of an application-side parent join.
TENANT_TABLES = (
    "workspaces",
    "memberships",
    "workspace_memberships",
    "agreements",
    "processing_jobs",
    "agreement_deletion_audit_events",
    "legal_playbooks",
    "playbook_versions",
    "playbook_rules",
    "playbook_audit_events",
    "playbook_evaluations",
    "playbook_findings",
    "review_decisions",
    "review_audit_events",
    "mcp_audit_events",
    "retrieval_index_builds",
    "retrieval_chunks",
    "retrieval_chunk_embeddings",
    "question_threads",
    "question_turns",
    "question_audit_events",
    "agreement_versions",
    "agreement_version_audit_events",
    "version_comparison_runs",
    "version_comparison_changes",
    "audit_events",
    "approval_policies",
    "approval_policy_versions",
    "approval_policy_stages",
    "approval_policy_audit_events",
    "review_cases",
    "review_assignments",
    "review_comments",
    "review_notification_events",
    "review_workflows",
    "review_workflow_stages",
    "review_workflow_decisions",
    "review_workflow_outbox",
    "review_final_packages",
    "processing_artifacts",
    "processing_outbox",
)

# These tables already had tenant policies in earlier revisions.  Downgrade
# intentionally leaves their pre-existing protections intact.
PREEXISTING_RLS_TABLES = {
    "workspaces",
    "memberships",
    "workspace_memberships",
    "agreements",
    "legal_playbooks",
    "playbook_versions",
    "playbook_rules",
    "playbook_audit_events",
    "playbook_evaluations",
    "playbook_findings",
    "review_decisions",
    "review_audit_events",
    "retrieval_index_builds",
    "retrieval_chunks",
    "retrieval_chunk_embeddings",
    "question_threads",
    "question_turns",
    "question_audit_events",
    "agreement_versions",
    "agreement_version_audit_events",
    "audit_events",
}

NEWLY_PROTECTED_TABLES = tuple(
    table_name for table_name in TENANT_TABLES if table_name not in PREEXISTING_RLS_TABLES
)


def upgrade() -> None:
    _add_processing_child_scope_columns()
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_tenant_isolation()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _disable_postgresql_tenant_isolation()
    _remove_processing_child_scope_columns()


def _add_processing_child_scope_columns() -> None:
    for table_name in ("processing_artifacts", "processing_outbox"):
        op.add_column(table_name, sa.Column("organization_id", sa.Uuid(), nullable=True))
        op.add_column(table_name, sa.Column("workspace_id", sa.Uuid(), nullable=True))
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET organization_id = (
                    SELECT organization_id
                    FROM processing_jobs
                    WHERE processing_jobs.id = {table_name}.job_id
                ),
                    workspace_id = (
                    SELECT workspace_id
                    FROM processing_jobs
                    WHERE processing_jobs.id = {table_name}.job_id
                )
                """
            )
        )
    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.create_unique_constraint(
            "uq_processing_jobs_scope_id", ["organization_id", "workspace_id", "id"]
        )
    for table_name in ("processing_artifacts", "processing_outbox"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("organization_id", nullable=False)
            batch_op.alter_column("workspace_id", nullable=False)
            batch_op.create_foreign_key(
                f"fk_{table_name}_processing_job_scope",
                "processing_jobs",
                ["organization_id", "workspace_id", "job_id"],
                ["organization_id", "workspace_id", "id"],
            )
            batch_op.create_index(f"ix_{table_name}_organization_id", ["organization_id"])


def _remove_processing_child_scope_columns() -> None:
    for table_name in ("processing_artifacts", "processing_outbox"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_organization_id")
            batch_op.drop_constraint(f"fk_{table_name}_processing_job_scope", type_="foreignkey")
            batch_op.drop_column("workspace_id")
            batch_op.drop_column("organization_id")
    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.drop_constraint("uq_processing_jobs_scope_id", type_="unique")


def _enable_postgresql_tenant_isolation() -> None:
    for table_name in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for table_name in NEWLY_PROTECTED_TABLES:
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table_name} ON {table_name}
                FOR ALL
                USING (organization_id = current_setting('app.organization_id', true)::uuid)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::uuid)
            """
        )


def _disable_postgresql_tenant_isolation() -> None:
    for table_name in NEWLY_PROTECTED_TABLES:
        op.execute(f"DROP POLICY tenant_isolation_{table_name} ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
