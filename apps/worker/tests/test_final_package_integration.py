from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from threading import Barrier, Lock
from typing import Any, TypedDict
from uuid import UUID, uuid4

import boto3
import pytest
from agreement_intelligence_api.reviews.export import _render_pdf as _legacy_render_pdf
from agreement_intelligence_worker.final_package import (
    FINAL_PACKAGE_WORKER_ACTOR_ID,
    S3FinalPackageStorage,
    StoredPackageObject,
    TerminalReviewPackageGenerator,
)
from agreement_intelligence_worker.review_workflow import SQLAlchemyWorkflowEventProcessor
from agreement_intelligence_worker.workflow_outbox_relay import WorkflowOutboxRelay
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy import event as sqlalchemy_event
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
            if event_id not in self.calls:
                self.calls.append(event_id)


class _SeededTerminalEvent(TypedDict):
    organization_id: UUID
    workspace_id: UUID
    agreement_id: UUID
    review_id: UUID
    workflow_id: UUID
    event_id: UUID
    correlation_id: str


class _CompetingRelayPublisher:
    def __init__(self, already_published: UUID) -> None:
        self._barrier = Barrier(2)
        self._lock = Lock()
        self.published = [already_published]

    def publish(self, event: dict[str, object]) -> None:
        with self._lock:
            self.published.append(UUID(str(event["id"])))
        self._barrier.wait(timeout=10)


class _RecordingRelayPublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    def publish(self, event: dict[str, object]) -> None:
        self.published.append(event)


class _FailOncePackageStorage:
    def __init__(self, delegate: S3FinalPackageStorage) -> None:
        self._delegate = delegate
        self.failed = False

    def read(self, key: str) -> StoredPackageObject | None:
        return self._delegate.read(key)

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        if key.endswith("report.pdf") and not self.failed:
            self.failed = True
            raise RuntimeError("simulated partial package write")
        return self._delegate.put_immutable(key, content, content_type=content_type, sha256=sha256)


class _RecordingPackageStorage:
    def __init__(self, delegate: S3FinalPackageStorage) -> None:
        self._delegate = delegate
        self.put_keys: set[str] = set()

    def read(self, key: str) -> StoredPackageObject | None:
        return self._delegate.read(key)

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        created = self._delegate.put_immutable(
            key, content, content_type=content_type, sha256=sha256
        )
        self.put_keys.add(key)
        return created


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
    migration_role = f"migration_{uuid4().hex}"
    migration_password = uuid4().hex
    migration_engine: Engine | None = None
    migration_role_created = False
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
        command.upgrade(config, "20260825_0032")
        seeded = _seed_terminal_event(engine, include_terminal_event=False)
        second_seeded = _seed_terminal_event(engine, include_terminal_event=False)
        legacy_seeded = _seed_terminal_event(engine, include_terminal_event=False)
        legacy_package = _seed_legacy_partial_package(engine, legacy_seeded)
        s3.create_bucket(Bucket=bucket)
        with base_engine.begin() as connection:
            connection.execute(
                text(
                    f'CREATE ROLE "{migration_role}" NOBYPASSRLS '
                    f"LOGIN PASSWORD '{migration_password}'"
                )
            )
        migration_role_created = True
        _transfer_schema_ownership(engine, schema_name, migration_role)
        migration_url = make_url(scoped_url).set(
            username=migration_role, password=migration_password
        )
        migration_engine = create_engine(
            migration_url.render_as_string(hide_password=False).replace(
                "postgresql://", "postgresql+psycopg://", 1
            )
        )
        migration_config = Config(str(Path(__file__).parents[2] / "api" / "alembic.ini"))
        migration_config.set_main_option(
            "sqlalchemy.url",
            migration_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        with base_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :role"),
                    {"role": migration_role},
                )
                is False
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity "
                        "FROM pg_class WHERE oid = CAST(:table_name AS regclass)"
                    ),
                    {"table_name": f'"{schema_name}".review_workflow_outbox'},
                )
                is True
            )
        command.upgrade(migration_config, "head")
        backfilled = _backfilled_event(migration_engine, seeded)
        assert backfilled["delivered_at"] is None
        assert backfilled["processed_at"] is None
        assert backfilled["correlation_id"] == seeded["correlation_id"]
        assert backfilled["package_snapshot"]["state"] == "rejected"
        assert backfilled["package_snapshot"]["organization_id"] == str(seeded["organization_id"])
        package_base = (
            f"reviews/{seeded['organization_id']}/{seeded['workspace_id']}/"
            f"{seeded['review_id']}/final-package"
        )
        assert backfilled["package_manifest_key"] == f"{package_base}/manifest.json"
        assert backfilled["package_pdf_key"] == f"{package_base}/report.pdf"
        assert backfilled["package_snapshot"]["manifest_key"] == backfilled["package_manifest_key"]
        assert backfilled["package_snapshot"]["pdf_key"] == backfilled["package_pdf_key"]
        assert backfilled["package_snapshot"]["provenance"]["workflow_event_id"] == str(
            backfilled["id"]
        )
        with (
            pytest.raises(Exception, match="ck_review_workflow_outbox_terminal_package"),
            migration_engine.begin() as connection,
        ):
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(seeded["organization_id"])},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO review_workflow_outbox (
                        id, workflow_id, organization_id, workspace_id, event_type,
                        correlation_id, idempotency_key, delivered_at, processed_at
                    ) VALUES (
                        :id, :workflow_id, :organization_id, :workspace_id,
                        'review.workflow.terminal', 'invalid-terminal-package',
                        :idempotency_key, NULL, NULL
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "workflow_id": seeded["workflow_id"],
                    "organization_id": seeded["organization_id"],
                    "workspace_id": seeded["workspace_id"],
                    "idempotency_key": f"invalid-terminal-package-{uuid4()}",
                },
            )
        seeded["event_id"] = backfilled["id"]
        seeded["correlation_id"] = backfilled["correlation_id"]
        second_backfilled = _backfilled_event(migration_engine, second_seeded)
        assert second_backfilled["package_snapshot"]["organization_id"] == str(
            second_seeded["organization_id"]
        )
        assert _tenant_backfill_count(migration_engine, seeded) == 1
        assert _tenant_backfill_count(migration_engine, second_seeded) == 1
        second_seeded["event_id"] = second_backfilled["id"]
        second_seeded["correlation_id"] = second_backfilled["correlation_id"]
        legacy_backfilled = _backfilled_event(migration_engine, legacy_seeded)
        legacy_recovery_base = (
            f"reviews/{legacy_seeded['organization_id']}/{legacy_seeded['workspace_id']}/"
            f"{legacy_seeded['review_id']}/final-package/recovery-0035"
        )
        assert legacy_backfilled["package_manifest_key"] == (
            f"{legacy_recovery_base}/manifest.json"
        )
        assert legacy_backfilled["package_pdf_key"] == f"{legacy_recovery_base}/report.pdf"
        assert (
            legacy_backfilled["package_snapshot"]["legacy_manifest_key"]
            == (legacy_package["manifest_key"])
        )
        assert (
            legacy_backfilled["package_snapshot"]["legacy_pdf_key"] == (legacy_package["pdf_key"])
        )
        legacy_repair = legacy_backfilled["package_snapshot"]["repair"]
        assert legacy_repair["legacy_workflow_id"] == str(legacy_package["workflow_id"])
        assert legacy_repair["legacy_state"] == legacy_package["state"]
        assert legacy_repair["legacy_manifest_checksum"] == legacy_package["manifest_checksum"]
        assert legacy_repair["legacy_pdf_checksum"] == legacy_package["pdf_checksum"]
        legacy_seeded["event_id"] = legacy_backfilled["id"]
        legacy_seeded["correlation_id"] = legacy_backfilled["correlation_id"]
        checkpoints = _ConcurrentCheckpointStore()
        object_storage = S3FinalPackageStorage(client=s3, bucket=bucket)
        partial_storage = _FailOncePackageStorage(object_storage)
        partial_processor = SQLAlchemyWorkflowEventProcessor(
            migration_engine,
            checkpoints,
            TerminalReviewPackageGenerator(partial_storage),
        )
        with pytest.raises(RuntimeError, match="simulated partial package write"):
            partial_processor.process(
                seeded["event_id"],
                organization_id=seeded["organization_id"],
                workspace_id=seeded["workspace_id"],
            )
        object_base = (
            f"reviews/{seeded['organization_id']}/{seeded['workspace_id']}/"
            f"{seeded['review_id']}/final-package"
        )
        frozen_manifest = s3.get_object(Bucket=bucket, Key=f"{object_base}/manifest.json")[
            "Body"
        ].read()
        frozen_provenance = loads(frozen_manifest)["provenance"]
        with pytest.raises(RuntimeError, match="remain unprocessed"):
            command.downgrade(migration_config, "20260825_0032")
        assert _backfilled_event(migration_engine, seeded)["id"] == seeded["event_id"]

        packages = TerminalReviewPackageGenerator(object_storage)

        def process() -> bool:
            return SQLAlchemyWorkflowEventProcessor(
                migration_engine, checkpoints, packages
            ).process(
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
        assert manifest == frozen_manifest
        assert loads(manifest)["provenance"] == frozen_provenance

        legacy_expected_keys = {
            legacy_backfilled["package_manifest_key"],
            legacy_backfilled["package_pdf_key"],
        }
        legacy_failure_storage = _RecordingPackageStorage(object_storage)
        fail_legacy_commit = True

        def fail_legacy_commit_after_storage(_: object) -> None:
            nonlocal fail_legacy_commit
            if fail_legacy_commit and legacy_expected_keys <= legacy_failure_storage.put_keys:
                fail_legacy_commit = False
                raise RuntimeError("simulated legacy repair commit failure after storage")

        sqlalchemy_event.listen(migration_engine, "commit", fail_legacy_commit_after_storage)
        try:
            with pytest.raises(RuntimeError, match="legacy repair commit failure after storage"):
                SQLAlchemyWorkflowEventProcessor(
                    migration_engine,
                    checkpoints,
                    TerminalReviewPackageGenerator(legacy_failure_storage),
                ).process(
                    legacy_seeded["event_id"],
                    organization_id=legacy_seeded["organization_id"],
                    workspace_id=legacy_seeded["workspace_id"],
                )
        finally:
            sqlalchemy_event.remove(migration_engine, "commit", fail_legacy_commit_after_storage)
        with migration_engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(legacy_seeded["organization_id"])},
            )
            failed_legacy_repair = (
                connection.execute(
                    text(
                        "SELECT package.manifest_key, package.pdf_key, event.processed_at "
                        "FROM review_final_packages AS package "
                        "JOIN review_workflows AS workflow "
                        "ON workflow.review_id = package.review_id "
                        "JOIN review_workflow_outbox AS event "
                        "ON event.workflow_id = workflow.id "
                        "WHERE package.id = :package_id AND event.id = :event_id"
                    ),
                    {
                        "package_id": legacy_package["id"],
                        "event_id": legacy_seeded["event_id"],
                    },
                )
                .mappings()
                .one()
            )
        assert failed_legacy_repair["manifest_key"] == legacy_package["manifest_key"]
        assert failed_legacy_repair["pdf_key"] == legacy_package["pdf_key"]
        assert failed_legacy_repair["processed_at"] is None
        legacy_retry_storage = _RecordingPackageStorage(object_storage)
        assert (
            SQLAlchemyWorkflowEventProcessor(
                migration_engine,
                checkpoints,
                TerminalReviewPackageGenerator(legacy_retry_storage),
            ).process(
                legacy_seeded["event_id"],
                organization_id=legacy_seeded["organization_id"],
                workspace_id=legacy_seeded["workspace_id"],
            )
            is True
        )
        assert legacy_retry_storage.put_keys == set()
        with migration_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(legacy_seeded["organization_id"])},
            )
            repaired_legacy_package = (
                connection.execute(
                    text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
                    {"review_id": legacy_seeded["review_id"]},
                )
                .mappings()
                .one()
            )
            repaired_legacy_audit = (
                connection.execute(
                    text(
                        "SELECT * FROM audit_events "
                        "WHERE action = 'review_final_package_generated' "
                        "AND resource_id = :package_id"
                    ),
                    {"package_id": legacy_package["id"]},
                )
                .mappings()
                .one()
            )
            connection.execute(
                text(
                    "UPDATE review_workflow_outbox SET delivered_at = CURRENT_TIMESTAMP "
                    "WHERE id = :event_id"
                ),
                {"event_id": legacy_seeded["event_id"]},
            )
        assert repaired_legacy_package["id"] == legacy_package["id"]
        assert (
            repaired_legacy_package["manifest_key"] == (legacy_backfilled["package_manifest_key"])
        )
        assert repaired_legacy_package["pdf_key"] == legacy_backfilled["package_pdf_key"]
        repaired_legacy_manifest = s3.get_object(
            Bucket=bucket, Key=repaired_legacy_package["manifest_key"]
        )["Body"].read()
        repaired_legacy_pdf = s3.get_object(Bucket=bucket, Key=repaired_legacy_package["pdf_key"])[
            "Body"
        ].read()
        assert (
            sha256(repaired_legacy_manifest).hexdigest()
            == repaired_legacy_package["manifest_checksum"]
        )
        assert sha256(repaired_legacy_pdf).hexdigest() == repaired_legacy_package["pdf_checksum"]
        assert repaired_legacy_audit["actor_id"] == FINAL_PACKAGE_WORKER_ACTOR_ID

        second_processor = SQLAlchemyWorkflowEventProcessor(migration_engine, checkpoints, packages)
        assert (
            second_processor.process(
                second_seeded["event_id"],
                organization_id=second_seeded["organization_id"],
                workspace_id=second_seeded["workspace_id"],
            )
            is True
        )
        command.downgrade(migration_config, "20260825_0032")
        command.upgrade(migration_config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM review_final_packages")) == 3
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE action = 'review_final_package_generated'"
                    )
                )
                == 3
            )
            retained = (
                connection.execute(
                    text(
                        "SELECT id, correlation_id FROM review_workflow_outbox "
                        "WHERE id IN (:first, :second) ORDER BY id"
                    ),
                    {"first": seeded["event_id"], "second": second_seeded["event_id"]},
                )
                .mappings()
                .all()
            )
            retained_audit = (
                connection.execute(
                    text(
                        "SELECT id, correlation_id, metadata_json FROM audit_events "
                        "WHERE action = 'review_final_package_generated' "
                        "ORDER BY occurred_at, id"
                    )
                )
                .mappings()
                .all()
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM review_workflow_outbox "
                        "WHERE idempotency_key LIKE :pattern"
                    ),
                    {"pattern": "workflow:%:terminal-package-backfill:0035"},
                )
                == 3
            )
        assert {item["id"] for item in retained} == {
            seeded["event_id"],
            second_seeded["event_id"],
        }
        assert {item["correlation_id"] for item in retained} == {
            seeded["correlation_id"],
            second_seeded["correlation_id"],
        }
        assert audit["id"] in {item["id"] for item in retained_audit}
        assert any(
            item["metadata_json"]["event_id"] == str(seeded["event_id"])
            and item["correlation_id"] == seeded["correlation_id"]
            for item in retained_audit
        )
        assert (
            s3.get_object(Bucket=bucket, Key=package["manifest_key"])["Body"].read()
            == frozen_manifest
        )

        ordinary_event = _seed_terminal_event(engine)
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(ordinary_event["organization_id"])},
            )
            ordinary_source = (
                connection.execute(
                    text(
                        "SELECT idempotency_key, package_snapshot "
                        "FROM review_workflow_outbox WHERE id = :event_id"
                    ),
                    {"event_id": ordinary_event["event_id"]},
                )
                .mappings()
                .one()
            )
        assert not ordinary_source["idempotency_key"].endswith("terminal-package-backfill:0035")
        assert ordinary_source["package_snapshot"] is not None
        ordinary_partial_storage = _FailOncePackageStorage(object_storage)
        ordinary_partial_processor = SQLAlchemyWorkflowEventProcessor(
            migration_engine,
            checkpoints,
            TerminalReviewPackageGenerator(ordinary_partial_storage),
        )
        with pytest.raises(RuntimeError, match="simulated partial package write"):
            ordinary_partial_processor.process(
                ordinary_event["event_id"],
                organization_id=ordinary_event["organization_id"],
                workspace_id=ordinary_event["workspace_id"],
            )
        ordinary_base = (
            f"reviews/{ordinary_event['organization_id']}/{ordinary_event['workspace_id']}/"
            f"{ordinary_event['review_id']}/final-package"
        )
        ordinary_manifest = s3.get_object(Bucket=bucket, Key=f"{ordinary_base}/manifest.json")[
            "Body"
        ].read()
        with pytest.raises(RuntimeError, match="remain unprocessed"):
            command.downgrade(migration_config, "20260825_0032")

        assert (
            SQLAlchemyWorkflowEventProcessor(migration_engine, checkpoints, packages).process(
                ordinary_event["event_id"],
                organization_id=ordinary_event["organization_id"],
                workspace_id=ordinary_event["workspace_id"],
            )
            is True
        )
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(ordinary_event["organization_id"])},
            )
            ordinary_package = (
                connection.execute(
                    text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
                    {"review_id": ordinary_event["review_id"]},
                )
                .mappings()
                .one()
            )
        recovered_ordinary_manifest = s3.get_object(
            Bucket=bucket, Key=ordinary_package["manifest_key"]
        )["Body"].read()
        ordinary_pdf = s3.get_object(Bucket=bucket, Key=ordinary_package["pdf_key"])["Body"].read()
        assert recovered_ordinary_manifest == ordinary_manifest
        assert (
            sha256(recovered_ordinary_manifest).hexdigest() == ordinary_package["manifest_checksum"]
        )
        assert sha256(ordinary_pdf).hexdigest() == ordinary_package["pdf_checksum"]

        commit_failure_event = _seed_terminal_event(engine)
        commit_failure_base = (
            f"reviews/{commit_failure_event['organization_id']}/"
            f"{commit_failure_event['workspace_id']}/"
            f"{commit_failure_event['review_id']}/final-package"
        )
        expected_commit_failure_keys = {
            f"{commit_failure_base}/manifest.json",
            f"{commit_failure_base}/report.pdf",
        }
        commit_failure_storage = _RecordingPackageStorage(object_storage)
        fail_commit = True

        def fail_after_storage(_: object) -> None:
            nonlocal fail_commit
            if fail_commit and expected_commit_failure_keys <= commit_failure_storage.put_keys:
                fail_commit = False
                raise RuntimeError("simulated database commit failure after storage")

        sqlalchemy_event.listen(migration_engine, "commit", fail_after_storage)
        try:
            with pytest.raises(RuntimeError, match="database commit failure after storage"):
                SQLAlchemyWorkflowEventProcessor(
                    migration_engine,
                    checkpoints,
                    TerminalReviewPackageGenerator(commit_failure_storage),
                ).process(
                    commit_failure_event["event_id"],
                    organization_id=commit_failure_event["organization_id"],
                    workspace_id=commit_failure_event["workspace_id"],
                )
        finally:
            sqlalchemy_event.remove(migration_engine, "commit", fail_after_storage)
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(commit_failure_event["organization_id"])},
            )
            failed_commit_event = (
                connection.execute(
                    text(
                        "SELECT processed_at, package_manifest_key, package_pdf_key "
                        "FROM review_workflow_outbox WHERE id=:event_id"
                    ),
                    {"event_id": commit_failure_event["event_id"]},
                )
                .mappings()
                .one()
            )
            assert failed_commit_event["processed_at"] is None
            assert {
                failed_commit_event["package_manifest_key"],
                failed_commit_event["package_pdf_key"],
            } == expected_commit_failure_keys
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM review_final_packages WHERE review_id=:review_id"),
                    {"review_id": commit_failure_event["review_id"]},
                )
                == 0
            )
        assert (
            SQLAlchemyWorkflowEventProcessor(migration_engine, checkpoints, packages).process(
                commit_failure_event["event_id"],
                organization_id=commit_failure_event["organization_id"],
                workspace_id=commit_failure_event["workspace_id"],
            )
            is True
        )
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(commit_failure_event["organization_id"])},
            )
            recovered_after_commit_failure = (
                connection.execute(
                    text("SELECT * FROM review_final_packages WHERE review_id=:review_id"),
                    {"review_id": commit_failure_event["review_id"]},
                )
                .mappings()
                .one()
            )
        assert (
            sha256(
                s3.get_object(Bucket=bucket, Key=recovered_after_commit_failure["manifest_key"])[
                    "Body"
                ].read()
            ).hexdigest()
            == recovered_after_commit_failure["manifest_checksum"]
        )

        assert (
            SQLAlchemyWorkflowEventProcessor(migration_engine, checkpoints, packages).process(
                seeded["event_id"],
                organization_id=seeded["organization_id"],
                workspace_id=seeded["workspace_id"],
            )
            is False
        )

        busy_tenant, later_tenant = sorted(
            (seeded, second_seeded), key=lambda item: str(item["organization_id"])
        )
        extra_busy_event_id = uuid4()
        with migration_engine.begin() as connection:
            for event in (busy_tenant, later_tenant):
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(event["organization_id"])},
                )
                connection.execute(
                    text(
                        "UPDATE review_workflow_outbox SET delivered_at = NULL, "
                        "lease_owner = NULL, lease_expires_at = NULL "
                        "WHERE id = :event_id"
                    ),
                    {"event_id": event["event_id"]},
                )
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(busy_tenant["organization_id"])},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO review_workflow_outbox (
                        id, workflow_id, organization_id, workspace_id, event_type,
                        correlation_id, idempotency_key, delivered_at, processed_at
                    ) VALUES (
                        :id, :workflow_id, :organization_id, :workspace_id,
                        'review.workflow.resume', 'relay-fairness', :idempotency_key,
                        NULL, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": extra_busy_event_id,
                    "workflow_id": busy_tenant["workflow_id"],
                    "organization_id": busy_tenant["organization_id"],
                    "workspace_id": busy_tenant["workspace_id"],
                    "idempotency_key": f"relay-fairness-{extra_busy_event_id}",
                },
            )
        fair_publisher = _RecordingRelayPublisher()
        fair_relay = WorkflowOutboxRelay(migration_engine, fair_publisher, owner="relay-fairness")
        assert fair_relay.relay_once() is True
        assert fair_relay.relay_once() is True
        assert [item["organization_id"] for item in fair_publisher.published] == [
            busy_tenant["organization_id"],
            later_tenant["organization_id"],
        ]
        with migration_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(busy_tenant["organization_id"])},
            )
            connection.execute(
                text("DELETE FROM review_workflow_outbox WHERE id = :event_id"),
                {"event_id": extra_busy_event_id},
            )

        with engine.begin() as connection:
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
        publisher = _CompetingRelayPublisher(seeded["event_id"])
        relays = (
            WorkflowOutboxRelay(migration_engine, publisher, owner="relay-a"),
            WorkflowOutboxRelay(migration_engine, publisher, owner="relay-b"),
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
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.organization_id', :organization_id, true)"),
                {"organization_id": str(commit_failure_event["organization_id"])},
            )
            connection.execute(
                text(
                    "UPDATE agreements SET deletion_requested_at=CURRENT_TIMESTAMP "
                    "WHERE id=:agreement_id"
                ),
                {"agreement_id": commit_failure_event["agreement_id"]},
            )
            connection.execute(
                text("DELETE FROM review_final_packages WHERE review_id=:review_id"),
                {"review_id": commit_failure_event["review_id"]},
            )
            connection.execute(
                text("DELETE FROM review_workflow_outbox WHERE id=:event_id"),
                {"event_id": commit_failure_event["event_id"]},
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM review_final_packages WHERE review_id=:review_id"),
                    {"review_id": commit_failure_event["review_id"]},
                )
                == 0
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM review_workflow_outbox WHERE id=:event_id"),
                    {"event_id": commit_failure_event["event_id"]},
                )
                == 0
            )
    finally:
        try:
            listed = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
            for item in listed:
                s3.delete_object(Bucket=bucket, Key=item["Key"])
            s3.delete_bucket(Bucket=bucket)
        except Exception:
            pass
        if migration_engine is not None:
            migration_engine.dispose()
        engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
            if migration_role_created:
                connection.execute(text(f'DROP OWNED BY "{migration_role}"'))
                connection.execute(text(f'DROP ROLE "{migration_role}"'))
        base_engine.dispose()


def _transfer_schema_ownership(engine: Engine, schema_name: str, role: str) -> None:
    with engine.begin() as connection:
        tables = connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = :schema_name"),
            {"schema_name": schema_name},
        ).scalars()
        sequences = connection.execute(
            text("SELECT sequencename FROM pg_sequences WHERE schemaname = :schema_name"),
            {"schema_name": schema_name},
        ).scalars()
        for table_name in tables:
            connection.execute(
                text(f'ALTER TABLE "{schema_name}"."{table_name}" OWNER TO "{role}"')
            )
        for sequence_name in sequences:
            connection.execute(
                text(f'ALTER SEQUENCE "{schema_name}"."{sequence_name}" OWNER TO "{role}"')
            )
        connection.execute(text(f'ALTER SCHEMA "{schema_name}" OWNER TO "{role}"'))


def _backfilled_event(engine: Engine, seeded: _SeededTerminalEvent) -> dict[str, Any]:
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(seeded["organization_id"])},
        )
        return dict(
            connection.execute(
                text(
                    "SELECT id, correlation_id, package_snapshot, package_manifest_key, "
                    "package_pdf_key, delivered_at, processed_at "
                    "FROM review_workflow_outbox "
                    "WHERE organization_id = :organization_id "
                    "AND workspace_id = :workspace_id "
                    "AND idempotency_key = :idempotency_key"
                ),
                {
                    "organization_id": seeded["organization_id"],
                    "workspace_id": seeded["workspace_id"],
                    "idempotency_key": (
                        f"workflow:{seeded['workflow_id']}:terminal-package-backfill:0035"
                    ),
                },
            )
            .mappings()
            .one()
        )


def _tenant_backfill_count(engine: Engine, seeded: _SeededTerminalEvent) -> int:
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(seeded["organization_id"])},
        )
        return int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM review_workflow_outbox "
                    "WHERE organization_id = :organization_id "
                    "AND idempotency_key LIKE :pattern"
                ),
                {
                    "organization_id": seeded["organization_id"],
                    "pattern": "workflow:%:terminal-package-backfill:0035",
                },
            )
            or 0
        )


def _seed_terminal_event(
    engine: Engine, *, include_terminal_event: bool = True
) -> _SeededTerminalEvent:
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
    package_base = f"reviews/{organization_id}/{workspace_id}/{review_id}/final-package"
    manifest_key = f"{package_base}/manifest.json"
    pdf_key = f"{package_base}/report.pdf"
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
        if include_terminal_event:
            connection.execute(
                text(
                    """
                INSERT INTO review_workflow_outbox (
                    id, workflow_id, organization_id, workspace_id, event_type,
                    correlation_id, idempotency_key, package_snapshot,
                    package_manifest_key, package_pdf_key, delivered_at, processed_at
                ) VALUES (
                    :id, :workflow_id, :organization_id, :workspace_id,
                    'review.workflow.terminal', :correlation_id,
                    :event_key, CAST(:package_snapshot AS JSONB),
                    :manifest_key, :pdf_key, CURRENT_TIMESTAMP, NULL
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
                            "manifest_key": manifest_key,
                            "pdf_key": pdf_key,
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
                    "manifest_key": manifest_key,
                    "pdf_key": pdf_key,
                },
            )
        else:
            connection.execute(
                text(
                    """
                    INSERT INTO review_workflow_outbox (
                        id, workflow_id, organization_id, workspace_id, event_type,
                        correlation_id, idempotency_key, delivered_at, processed_at
                    ) VALUES (
                        :id, :workflow_id, :organization_id, :workspace_id,
                        'review.workflow.resume', :correlation_id, :event_key,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": event_id,
                    "workflow_id": workflow_id,
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "correlation_id": correlation_id,
                    "event_key": f"terminal-integration-old-processed-{event_id}",
                },
            )
    return {
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "agreement_id": agreement_id,
        "review_id": review_id,
        "workflow_id": workflow_id,
        "event_id": event_id,
        "correlation_id": correlation_id,
    }


def _seed_legacy_partial_package(
    engine: Engine, seeded: _SeededTerminalEvent
) -> dict[str, UUID | str]:
    package_id = uuid4()
    package_base = (
        f"reviews/{seeded['organization_id']}/{seeded['workspace_id']}/"
        f"{seeded['review_id']}/final-package"
    )
    manifest_key = f"{package_base}/manifest.json"
    pdf_key = f"{package_base}/report.pdf"
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.organization_id', :organization_id, true)"),
            {"organization_id": str(seeded["organization_id"])},
        )
        workflow = (
            connection.execute(
                text(
                    "SELECT policy_version_id, state, revision FROM review_workflows "
                    "WHERE id = :workflow_id"
                ),
                {"workflow_id": seeded["workflow_id"]},
            )
            .mappings()
            .one()
        )
        legacy_manifest = {
            "review_id": str(seeded["review_id"]),
            "agreement_id": str(seeded["agreement_id"]),
            "agreement_version_id": None,
            "workflow_id": str(seeded["workflow_id"]),
            "policy_version_id": str(workflow["policy_version_id"]),
            "state": workflow["state"],
            "revision": workflow["revision"],
            "decisions": [],
            "stages": [],
            "assignments": [],
            "comments": [],
            "findings": [],
            "audit_event_ids": [],
            "provenance": {"source": "postgresql", "workflow_revision": 1},
        }
        manifest_content = dumps(legacy_manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest_checksum = sha256(manifest_content).hexdigest()
        pdf_content = _legacy_render_pdf(
            [
                "Agreement Intelligence - Final Review Package",
                f"Agreement ID: {seeded['agreement_id']}",
                f"Review ID: {seeded['review_id']}",
                "Outcome: rejected",
                f"Manifest checksum: sha256:{manifest_checksum}",
            ]
        )
        connection.execute(
            text(
                """
                INSERT INTO review_final_packages (
                    id, organization_id, workspace_id, review_id, workflow_id, state,
                    manifest_key, pdf_key, manifest_checksum, pdf_checksum
                ) VALUES (
                    :id, :organization_id, :workspace_id, :review_id, :workflow_id,
                    'rejected', :manifest_key, :pdf_key, :manifest_checksum, :pdf_checksum
                )
                """
            ),
            {
                "id": package_id,
                "organization_id": seeded["organization_id"],
                "workspace_id": seeded["workspace_id"],
                "review_id": seeded["review_id"],
                "workflow_id": seeded["workflow_id"],
                "manifest_key": manifest_key,
                "pdf_key": pdf_key,
                "manifest_checksum": manifest_checksum,
                "pdf_checksum": sha256(pdf_content).hexdigest(),
            },
        )
    return {
        "id": package_id,
        "workflow_id": seeded["workflow_id"],
        "state": "rejected",
        "manifest_key": manifest_key,
        "pdf_key": pdf_key,
        "manifest_checksum": manifest_checksum,
        "pdf_checksum": sha256(pdf_content).hexdigest(),
    }
