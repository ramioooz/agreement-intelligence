from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from json import loads
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

import boto3
import pytest
from agreement_intelligence_worker.final_package import (
    FINAL_PACKAGE_WORKER_ACTOR_ID,
    S3FinalPackageStorage,
    TerminalReviewPackageGenerator,
)
from agreement_intelligence_worker.review_workflow import SQLAlchemyWorkflowEventProcessor
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url


class _ConcurrentCheckpointStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.calls: list[UUID] = []

    def persist(
        self,
        *,
        event_id: UUID,
        checkpoint_id: UUID,
        workflow_id: UUID,
        event_type: str,
    ) -> None:
        with self._lock:
            self.calls.append(event_id)


def test_concurrent_terminal_delivery_creates_one_correlated_checksum_valid_package() -> None:
    """Exercises the migrated PostgreSQL lock and real conditional LocalStack object writes."""
    postgres_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    endpoint = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_LOCALSTACK_URL")
    if not postgres_url or not endpoint:
        pytest.skip("disposable PostgreSQL and LocalStack endpoints are required")

    schema_name = f"terminal_package_{uuid4().hex}"
    scoped_url = make_url(postgres_url).set(
        query={"options": f"-csearch_path={schema_name},public"}
    ).render_as_string(hide_password=False)
    base_engine = create_engine(postgres_url.replace("postgresql://", "postgresql+psycopg://", 1))
    engine = create_engine(scoped_url.replace("postgresql://", "postgresql+psycopg://", 1))
    bucket = f"terminal-packages-{uuid4().hex}"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    try:
        config = Config(
            str(
                Path(__file__).parents[2]
                / "api"
                / "alembic.ini"
            )
        )
        config.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
        command.upgrade(config, "head")
        seeded = _seed_terminal_event(engine)
        s3.create_bucket(Bucket=bucket)
        checkpoints = _ConcurrentCheckpointStore()
        packages = TerminalReviewPackageGenerator(
            S3FinalPackageStorage(client=s3, bucket=bucket)
        )

        def process() -> bool:
            return SQLAlchemyWorkflowEventProcessor(engine, checkpoints, packages).process(
                seeded["event_id"],
                organization_id=seeded["organization_id"],
                workspace_id=seeded["workspace_id"],
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(process)
            second = executor.submit(process)
            outcomes = sorted((first.result(), second.result()))

        assert outcomes == [False, True]
        assert checkpoints.calls == [seeded["event_id"]]
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(seeded["organization_id"])},
            )
            package = connection.execute(
                text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
                {"review_id": seeded["review_id"]},
            ).mappings().one()
            audit = connection.execute(
                text(
                    "SELECT * FROM audit_events "
                    "WHERE action = 'review_final_package_generated'"
                )
            ).mappings().one()
        manifest = s3.get_object(Bucket=bucket, Key=package["manifest_key"])["Body"].read()
        pdf = s3.get_object(Bucket=bucket, Key=package["pdf_key"])["Body"].read()
        assert sha256(manifest).hexdigest() == package["manifest_checksum"]
        assert sha256(pdf).hexdigest() == package["pdf_checksum"]
        assert loads(manifest)["provenance"]["workflow_correlation_id"] == seeded[
            "correlation_id"
        ]
        assert audit["actor_id"] == FINAL_PACKAGE_WORKER_ACTOR_ID
        assert audit["correlation_id"] == seeded["correlation_id"]
    finally:
        try:
            listed = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
            for item in listed:
                s3.delete_object(Bucket=bucket, Key=item["Key"])
            s3.delete_bucket(Bucket=bucket)
        except Exception:
            pass
        engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        base_engine.dispose()


def _seed_terminal_event(engine: Engine) -> dict[str, UUID | str]:
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    review_id = uuid4()
    policy_id = uuid4()
    policy_version_id = uuid4()
    workflow_id = uuid4()
    event_id = uuid4()
    actor_id = uuid4()
    checkpoint_id = uuid4()
    correlation_id = "terminal-integration-correlation"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Test', :slug)"),
            {"id": organization_id, "slug": f"test-{organization_id}"},
        )
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(organization_id)},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, organization_id, name, slug) "
                "VALUES (:id, :organization_id, 'Test', :slug)"
            ),
            {
                "id": workspace_id,
                "organization_id": organization_id,
                "slug": f"test-{workspace_id}",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO agreements (
                    id, organization_id, workspace_id, title, agreement_type, status,
                    parties, files, processing_state, audit_metadata, audit_events
                ) VALUES (
                    :id, :organization_id, :workspace_id, 'Test', 'nda', 'draft',
                    '[]'::jsonb, '[]'::jsonb, 'completed', '{}'::jsonb, '[]'::jsonb
                )
                """
            ),
            {
                "id": agreement_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO approval_policies (
                    id, organization_id, workspace_id, name, agreement_family,
                    document_direction, jurisdiction, materiality, precedence, created_by
                ) VALUES (
                    :id, :organization_id, :workspace_id, 'Test', 'nda',
                    'any', 'any', 'any', 1, :actor_id
                )
                """
            ),
            {
                "id": policy_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "actor_id": actor_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO approval_policy_versions (
                    id, organization_id, workspace_id, policy_id, version, status,
                    submitter_may_approve, allow_cross_stage_same_approver, created_by
                ) VALUES (
                    :id, :organization_id, :workspace_id, :policy_id, 1, 'published',
                    false, false, :actor_id
                )
                """
            ),
            {
                "id": policy_version_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "policy_id": policy_id,
                "actor_id": actor_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO review_cases (
                    id, organization_id, workspace_id, agreement_id, state, created_by,
                    idempotency_key, revision
                ) VALUES (
                    :id, :organization_id, :workspace_id, :agreement_id, 'open', :actor_id,
                    'terminal-integration-review', 0
                )
                """
            ),
            {
                "id": review_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "actor_id": actor_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO review_workflows (
                    id, organization_id, workspace_id, review_id, policy_version_id,
                    checkpoint_id, state, active_stage_ordinal, revision
                ) VALUES (
                    :id, :organization_id, :workspace_id, :review_id, :policy_version_id,
                    :checkpoint_id, 'rejected', NULL, 1
                )
                """
            ),
            {
                "id": workflow_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "review_id": review_id,
                "policy_version_id": policy_version_id,
                "checkpoint_id": checkpoint_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO review_workflow_outbox (
                    id, workflow_id, organization_id, workspace_id, event_type,
                    correlation_id, idempotency_key, delivered_at, processed_at
                ) VALUES (
                    :id, :workflow_id, :organization_id, :workspace_id,
                    'review.workflow.terminal', :correlation_id,
                    'terminal-integration-event', CURRENT_TIMESTAMP, NULL
                )
                """
            ),
            {
                "id": event_id,
                "workflow_id": workflow_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "correlation_id": correlation_id,
            },
        )
    return {
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "review_id": review_id,
        "workflow_id": workflow_id,
        "event_id": event_id,
        "correlation_id": correlation_id,
    }
