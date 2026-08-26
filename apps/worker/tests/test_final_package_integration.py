from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from threading import Barrier, Lock
from uuid import UUID, uuid4

import boto3
import pytest
from agreement_intelligence_worker.final_package import (
    FINAL_PACKAGE_WORKER_ACTOR_ID,
    S3FinalPackageStorage,
    TerminalReviewPackageGenerator,
)
from agreement_intelligence_worker.review_workflow import SQLAlchemyWorkflowEventProcessor
from agreement_intelligence_worker.workflow_outbox_relay import WorkflowOutboxRelay
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


class _CompetingRelayPublisher:
    def __init__(self, already_published: UUID) -> None:
        self._barrier = Barrier(2)
        self._lock = Lock()
        self.published = [already_published]

    def publish(self, event: dict[str, object]) -> None:
        with self._lock:
            self.published.append(UUID(str(event["id"])))
        self._barrier.wait(timeout=10)


def test_concurrent_terminal_delivery_creates_one_correlated_checksum_valid_package() -> None:
    """Exercises the migrated PostgreSQL lock and real conditional LocalStack object writes."""
    postgres_url = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL")
    endpoint = os.environ.get("AGREEMENT_INTELLIGENCE_TEST_LOCALSTACK_URL")
    if not postgres_url or not endpoint:
        if os.environ.get("CI"):
            pytest.fail("CI must provide PostgreSQL and LocalStack for terminal package coverage")
        pytest.skip("disposable PostgreSQL and LocalStack endpoints are required")

    schema_name = f"terminal_package_{uuid4().hex}"
    scoped_url = (
        make_url(postgres_url)
        .set(query={"options": f"-csearch_path={schema_name},public"})
        .render_as_string(hide_password=False)
    )
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
        config = Config(str(Path(__file__).parents[2] / "api" / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
        command.upgrade(config, "head")
        seeded = _seed_terminal_event(engine)
        s3.create_bucket(Bucket=bucket)
        checkpoints = _ConcurrentCheckpointStore()
        packages = TerminalReviewPackageGenerator(S3FinalPackageStorage(client=s3, bucket=bucket))

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
            package = (
                connection.execute(
                    text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
                    {"review_id": seeded["review_id"]},
                )
                .mappings()
                .one()
            )
            audit = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events WHERE action = 'review_final_package_generated'"
                    )
                )
                .mappings()
                .one()
            )
        manifest = s3.get_object(Bucket=bucket, Key=package["manifest_key"])["Body"].read()
        pdf = s3.get_object(Bucket=bucket, Key=package["pdf_key"])["Body"].read()
        assert sha256(manifest).hexdigest() == package["manifest_checksum"]
        assert sha256(pdf).hexdigest() == package["pdf_checksum"]
        assert loads(manifest)["provenance"]["workflow_correlation_id"] == seeded["correlation_id"]
        assert audit["actor_id"] == FINAL_PACKAGE_WORKER_ACTOR_ID
        assert audit["correlation_id"] == seeded["correlation_id"]

        second_seeded = _seed_terminal_event(engine)
        relay_role = f"relay_{uuid4().hex}"
        relay_password = uuid4().hex
        with base_engine.begin() as connection:
            connection.execute(
                text(f"CREATE ROLE \"{relay_role}\" LOGIN PASSWORD '{relay_password}'")
            )
        with engine.begin() as connection:
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema_name}" TO "{relay_role}"'))
            connection.execute(text(f'GRANT SELECT ON organizations TO "{relay_role}"'))
            connection.execute(
                text(f'GRANT SELECT, UPDATE ON review_workflow_outbox TO "{relay_role}"')
            )
            for event in (seeded, second_seeded):
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(event["organization_id"])},
                )
                connection.execute(
                    text(
                        "UPDATE review_workflow_outbox SET delivered_at = NULL, "
                        "lease_owner = :owner, "
                        "lease_expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second' "
                        "WHERE id = :event_id"
                    ),
                    {
                        "owner": "crashed-after-publish" if event is seeded else None,
                        "event_id": event["event_id"],
                    },
                )
        relay_url = make_url(scoped_url).set(username=relay_role, password=relay_password)
        relay_engine = create_engine(
            relay_url.render_as_string(hide_password=False).replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        )
        publisher = _CompetingRelayPublisher(seeded["event_id"])  # type: ignore[arg-type]
        relays = (
            WorkflowOutboxRelay(relay_engine, publisher, owner="relay-a"),
            WorkflowOutboxRelay(relay_engine, publisher, owner="relay-b"),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            relay_results = [executor.submit(relay.relay_once) for relay in relays]
            assert [result.result() for result in relay_results] == [True, True]
        assert publisher.published.count(seeded["event_id"]) == 2
        assert publisher.published.count(second_seeded["event_id"]) == 1
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM review_workflow_outbox WHERE delivered_at IS NULL")
                )
                == 0
            )
        relay_engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{relay_role}"'))
            connection.execute(text(f'DROP ROLE "{relay_role}"'))
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
    correlation_id = f"terminal-integration-{event_id.hex[:16]}"
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
                    :review_key, 0
                )
                """
            ),
            {
                "id": review_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "agreement_id": agreement_id,
                "actor_id": actor_id,
                "review_key": f"terminal-integration-review-{review_id}",
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
                    correlation_id, idempotency_key, package_snapshot, delivered_at, processed_at
                ) VALUES (
                    :id, :workflow_id, :organization_id, :workspace_id,
                    'review.workflow.terminal', :correlation_id,
                    :event_key, CAST(:package_snapshot AS JSONB),
                    CURRENT_TIMESTAMP, NULL
                )
                """
            ),
            {
                "id": event_id,
                "workflow_id": workflow_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "correlation_id": correlation_id,
                "event_key": f"terminal-integration-event-{event_id}",
                "package_snapshot": dumps(
                    {
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id),
                        "review_id": str(review_id),
                        "agreement_id": str(agreement_id),
                        "agreement_version_id": None,
                        "workflow_id": str(workflow_id),
                        "policy_version_id": str(policy_version_id),
                        "state": "rejected",
                        "revision": 1,
                        "decisions": [],
                        "stages": [],
                        "assignments": [],
                        "comments": [],
                        "findings": [],
                        "audit_event_ids": [],
                        "provenance": {
                            "generator": "review-final-package-worker",
                            "source": "postgresql-terminal-snapshot",
                            "workflow_correlation_id": correlation_id,
                            "workflow_event_id": str(event_id),
                            "workflow_revision": 1,
                        },
                    },
                    sort_keys=True,
                ),
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
