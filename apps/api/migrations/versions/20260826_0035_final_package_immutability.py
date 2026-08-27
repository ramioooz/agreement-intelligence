"""Enforce final review package metadata immutability in PostgreSQL.

Revision ID: 20260826_0035
Revises: 20260826_0034
Create Date: 2026-08-26
"""

from collections.abc import Sequence
from json import dumps
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0035"
down_revision: str | None = "20260826_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("review_workflow_outbox", sa.Column("package_snapshot", sa.JSON(), nullable=True))
    op.add_column(
        "review_workflow_outbox",
        sa.Column("package_manifest_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "review_workflow_outbox",
        sa.Column("package_pdf_key", sa.String(length=1024), nullable=True),
    )
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
    _backfill_terminal_package_events()
    op.create_check_constraint(
        "ck_review_workflow_outbox_terminal_package",
        "review_workflow_outbox",
        "event_type <> 'review.workflow.terminal' OR processed_at IS NOT NULL OR "
        "(package_snapshot IS NOT NULL AND package_manifest_key IS NOT NULL "
        "AND package_pdf_key IS NOT NULL)",
    )
    op.execute(
        """
        CREATE FUNCTION prevent_review_final_package_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND EXISTS (
            SELECT 1
            FROM review_cases AS review
            JOIN agreements AS agreement ON agreement.id = review.agreement_id
            WHERE review.id = OLD.review_id
              AND review.organization_id = OLD.organization_id
              AND review.workspace_id = OLD.workspace_id
              AND agreement.deletion_requested_at IS NOT NULL
          ) THEN
            RETURN OLD;
          END IF;
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
              IF EXISTS (
                SELECT 1
                FROM review_workflows AS workflow
                JOIN review_cases AS review ON review.id = workflow.review_id
                JOIN agreements AS agreement ON agreement.id = review.agreement_id
                WHERE workflow.id = OLD.workflow_id
                  AND workflow.organization_id = OLD.organization_id
                  AND workflow.workspace_id = OLD.workspace_id
                  AND agreement.deletion_requested_at IS NOT NULL
              ) THEN
                RETURN OLD;
              END IF;
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
               OR NEW.package_manifest_key IS DISTINCT FROM OLD.package_manifest_key
               OR NEW.package_pdf_key IS DISTINCT FROM OLD.package_pdf_key
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
        _assert_terminal_snapshot_events_are_complete()
        op.drop_constraint(
            "ck_review_workflow_outbox_terminal_package",
            "review_workflow_outbox",
            type_="check",
        )
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
        "package_pdf_key",
        "package_manifest_key",
        "package_snapshot",
    ):
        op.drop_column("review_workflow_outbox", column)


def _backfill_terminal_package_events() -> None:
    connection = op.get_bind()
    organization_ids = list(
        connection.execute(sa.text("SELECT id FROM organizations ORDER BY id")).scalars()
    )
    for organization_id in organization_ids:
        connection.execute(
            sa.text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        workflows = list(
            connection.execute(
                sa.text(
                    """
                SELECT workflow.id AS workflow_id, workflow.organization_id,
                       workflow.workspace_id, workflow.review_id,
                       workflow.policy_version_id, workflow.state, workflow.revision,
                       review.agreement_id, review.agreement_version_id
                FROM review_workflows AS workflow
                JOIN review_cases AS review
                  ON review.id = workflow.review_id
                 AND review.organization_id = :organization_id
                 AND review.workspace_id = workflow.workspace_id
                WHERE workflow.organization_id = :organization_id
                  AND workflow.state IN ('approved', 'rejected', 'revision_requested')
                  AND NOT EXISTS (
                    SELECT 1 FROM review_final_packages AS package
                    WHERE package.review_id = workflow.review_id
                      AND package.organization_id = workflow.organization_id
                      AND package.workspace_id = workflow.workspace_id
                  )
                ORDER BY workflow.created_at, workflow.id
                    """
                ),
                {"organization_id": organization_id},
            ).mappings()
        )
        for workflow in workflows:
            _backfill_terminal_package_event(connection, workflow)


def _assert_terminal_snapshot_events_are_complete() -> None:
    connection = op.get_bind()
    organization_ids = list(
        connection.execute(sa.text("SELECT id FROM organizations ORDER BY id")).scalars()
    )
    for organization_id in organization_ids:
        connection.execute(
            sa.text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        incomplete = connection.scalar(
            sa.text(
                """
                SELECT count(*)
                FROM review_workflow_outbox AS event
                JOIN review_workflows AS workflow
                  ON workflow.id = event.workflow_id
                 AND workflow.organization_id = :organization_id
                 AND workflow.workspace_id = event.workspace_id
                WHERE event.organization_id = :organization_id
                  AND event.event_type = 'review.workflow.terminal'
                  AND event.package_snapshot IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM review_final_packages AS package
                    WHERE package.review_id = workflow.review_id
                      AND package.organization_id = workflow.organization_id
                      AND package.workspace_id = workflow.workspace_id
                  )
                """
            ),
            {"organization_id": organization_id},
        )
        if incomplete:
            raise RuntimeError(
                "cannot downgrade 0035 while terminal package snapshot events "
                "lack committed final-package metadata"
            )


def _backfill_terminal_package_event(connection: sa.Connection, workflow: sa.RowMapping) -> None:
    workflow_id = workflow["workflow_id"]
    review_id = workflow["review_id"]
    event_id = uuid4()
    package_base = (
        f"reviews/{workflow['organization_id']}/{workflow['workspace_id']}/"
        f"{review_id}/final-package"
    )
    manifest_key = f"{package_base}/manifest.json"
    pdf_key = f"{package_base}/report.pdf"
    correlation_id = (
        connection.scalar(
            sa.text(
                """
            SELECT correlation_id FROM review_workflow_outbox
            WHERE workflow_id = :workflow_id
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
            ),
            {
                "workflow_id": workflow_id,
                "organization_id": workflow["organization_id"],
                "workspace_id": workflow["workspace_id"],
            },
        )
        or f"migration-0035-{workflow_id}"
    )
    decisions = connection.execute(
        sa.text(
            """
            SELECT actor_id, action, workflow_stage_id, occurred_at
            FROM review_workflow_decisions
            WHERE workflow_id = :workflow_id
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
            ORDER BY occurred_at, id
            """
        ),
        {
            "workflow_id": workflow_id,
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
        },
    ).mappings()
    stages = connection.execute(
        sa.text(
            """
            SELECT id, ordinal, state, activated_at, completed_at
            FROM review_workflow_stages
            WHERE workflow_id = :workflow_id
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
            ORDER BY ordinal, id
            """
        ),
        {
            "workflow_id": workflow_id,
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
        },
    ).mappings()
    assignments = connection.execute(
        sa.text(
            """
            SELECT id, assignee_id, status, due_at
            FROM review_assignments
            WHERE review_id = :review_id
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
            ORDER BY created_at, id
            """
        ),
        {
            "review_id": review_id,
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
        },
    ).mappings()
    comments = connection.execute(
        sa.text(
            """
            SELECT id, author_id, finding_id, created_at
            FROM review_comments
            WHERE review_id = :review_id
              AND organization_id = :organization_id
              AND workspace_id = :workspace_id
            ORDER BY created_at, id
            """
        ),
        {
            "review_id": review_id,
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
        },
    ).mappings()
    findings = connection.execute(
        sa.text(
            """
            SELECT finding.id, finding.result, finding.severity, finding.citation_ids
            FROM playbook_findings AS finding
            JOIN playbook_evaluations AS evaluation ON evaluation.id = finding.evaluation_id
            WHERE finding.organization_id = :organization_id
              AND finding.workspace_id = :workspace_id
              AND evaluation.agreement_id = :agreement_id
            ORDER BY finding.id
            """
        ),
        {
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
            "agreement_id": workflow["agreement_id"],
        },
    ).mappings()
    audit_ids = connection.execute(
        sa.text(
            """
            SELECT id FROM audit_events
            WHERE organization_id = :organization_id
              AND workspace_id = :workspace_id
              AND resource_id = :review_id
            ORDER BY occurred_at, id
            """
        ),
        {
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
            "review_id": review_id,
        },
    ).scalars()
    snapshot = {
        "organization_id": str(workflow["organization_id"]),
        "workspace_id": str(workflow["workspace_id"]),
        "review_id": str(review_id),
        "agreement_id": str(workflow["agreement_id"]),
        "agreement_version_id": (
            str(workflow["agreement_version_id"])
            if workflow["agreement_version_id"] is not None
            else None
        ),
        "workflow_id": str(workflow_id),
        "policy_version_id": str(workflow["policy_version_id"]),
        "manifest_key": manifest_key,
        "pdf_key": pdf_key,
        "state": workflow["state"],
        "revision": workflow["revision"],
        "decisions": [
            {
                "actor_id": str(item["actor_id"]),
                "action": item["action"],
                "stage_id": str(item["workflow_stage_id"]),
                "occurred_at": _isoformat(item["occurred_at"]),
            }
            for item in decisions
        ],
        "stages": [
            {
                "id": str(item["id"]),
                "ordinal": item["ordinal"],
                "state": item["state"],
                "activated_at": _isoformat(item["activated_at"]),
                "completed_at": _isoformat(item["completed_at"]),
            }
            for item in stages
        ],
        "assignments": [
            {
                "id": str(item["id"]),
                "assignee_id": str(item["assignee_id"]),
                "status": item["status"],
                "due_at": _isoformat(item["due_at"]),
            }
            for item in assignments
        ],
        "comments": [
            {
                "id": str(item["id"]),
                "author_id": str(item["author_id"]),
                "finding_id": str(item["finding_id"]) if item["finding_id"] else None,
                "created_at": _isoformat(item["created_at"]),
            }
            for item in comments
        ],
        "findings": [
            {
                "id": str(item["id"]),
                "result": item["result"],
                "severity": item["severity"],
                "citation_ids": item["citation_ids"],
            }
            for item in findings
        ],
        "audit_event_ids": [str(item) for item in audit_ids],
        "provenance": {
            "generator": "review-final-package-worker",
            "source": "postgresql-terminal-migration-snapshot",
            "workflow_correlation_id": correlation_id,
            "workflow_event_id": str(event_id),
            "workflow_revision": workflow["revision"],
        },
    }
    connection.execute(
        sa.text(
            """
            INSERT INTO review_workflow_outbox (
                id, workflow_id, organization_id, workspace_id, event_type,
                correlation_id, idempotency_key, package_snapshot,
                package_manifest_key, package_pdf_key, delivered_at, processed_at,
                attempt_count, created_at
            ) VALUES (
                :id, :workflow_id, :organization_id, :workspace_id,
                'review.workflow.terminal', :correlation_id, :idempotency_key,
                CAST(:package_snapshot AS JSONB), :package_manifest_key,
                :package_pdf_key, NULL, NULL, 0, CURRENT_TIMESTAMP
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        ),
        {
            "id": event_id,
            "workflow_id": workflow_id,
            "organization_id": workflow["organization_id"],
            "workspace_id": workflow["workspace_id"],
            "correlation_id": correlation_id,
            "idempotency_key": f"workflow:{workflow_id}:terminal-package-backfill:0035",
            "package_snapshot": dumps(snapshot, sort_keys=True),
            "package_manifest_key": manifest_key,
            "package_pdf_key": pdf_key,
        },
    )


def _isoformat(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if not callable(isoformat):
        raise TypeError("package snapshot timestamps must support isoformat")
    return str(isoformat())
