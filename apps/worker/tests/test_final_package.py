from __future__ import annotations

from importlib import import_module
from json import dumps, loads
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text


def _final_package_module() -> ModuleType:
    try:
        return import_module("agreement_intelligence_worker.final_package")
    except ModuleNotFoundError:
        pytest.fail("terminal package generation must be owned by the durable worker")


class MemoryPackageStorage:
    def __init__(self) -> None:
        self.objects: dict[str, SimpleNamespace] = {}
        self.put_calls: list[str] = []
        self.fail_once_suffix: str | None = None

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        self.put_calls.append(key)
        if self.fail_once_suffix and key.endswith(self.fail_once_suffix):
            self.fail_once_suffix = None
            raise RuntimeError("storage unavailable")
        if key in self.objects:
            return False
        self.objects[key] = SimpleNamespace(content=content, content_type=content_type)
        return True

    def read(self, key: str) -> SimpleNamespace | None:
        return self.objects.get(key)


def test_worker_persists_one_checksum_verified_package_with_system_attribution() -> None:
    """Fails if package objects, immutable metadata, and audit provenance diverge."""
    module = _final_package_module()
    engine, seeded = _seed_terminal_workflow()
    storage = MemoryPackageStorage()
    generator = module.TerminalReviewPackageGenerator(storage)

    with engine.begin() as connection:
        first = generator.generate(
            connection,
            event_id=seeded["event_id"],
            workflow_id=seeded["workflow_id"],
            correlation_id="terminal-correlation-id",
        )
    first_put_calls = list(storage.put_calls)
    with engine.begin() as connection:
        second = generator.generate(
            connection,
            event_id=seeded["event_id"],
            workflow_id=seeded["workflow_id"],
            correlation_id="terminal-correlation-id",
        )

    assert first.package_id == second.package_id
    assert first.created is True
    assert second.created is False
    assert storage.put_calls == first_put_calls
    assert len(storage.objects) == 2
    with engine.connect() as connection:
        package = (
            connection.execute(
                text("SELECT * FROM review_final_packages WHERE review_id = :review_id"),
                {"review_id": str(seeded["review_id"])},
            )
            .mappings()
            .one()
        )
        audit = (
            connection.execute(
                text("SELECT * FROM audit_events WHERE action = 'review_final_package_generated'")
            )
            .mappings()
            .one()
        )
    manifest = storage.objects[package["manifest_key"]]
    pdf = storage.objects[package["pdf_key"]]
    assert module.sha256(manifest.content).hexdigest() == package["manifest_checksum"]
    assert module.sha256(pdf.content).hexdigest() == package["pdf_checksum"]
    assert pdf.content.startswith(b"%PDF-1.4")
    assert UUID(str(audit["actor_id"])) == module.FINAL_PACKAGE_WORKER_ACTOR_ID
    assert audit["correlation_id"] == "terminal-correlation-id"
    metadata = audit["metadata_json"]
    if isinstance(metadata, str):
        metadata = loads(metadata)
    assert metadata == {
        "actor_type": "system",
        "event_id": str(seeded["event_id"]),
        "review_id": str(seeded["review_id"]),
        "workflow_id": str(seeded["workflow_id"]),
        "worker": "review-final-package",
    }
    engine.dispose()


def test_worker_recovers_after_restart_from_a_partially_written_object_pair() -> None:
    """Fails if an immutable first object prevents a later retry completing metadata."""
    module = _final_package_module()
    engine, seeded = _seed_terminal_workflow()
    storage = MemoryPackageStorage()
    storage.fail_once_suffix = "report.pdf"

    with pytest.raises(RuntimeError, match="storage unavailable"), engine.begin() as connection:
        module.TerminalReviewPackageGenerator(storage).generate(
            connection,
            event_id=seeded["event_id"],
            workflow_id=seeded["workflow_id"],
            correlation_id="restart-correlation-id",
        )

    assert len(storage.objects) == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM review_final_packages")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM audit_events")) == 0

    original_manifest = next(
        item.content for key, item in storage.objects.items() if key.endswith("manifest.json")
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO review_comments VALUES "
                "(:id, :review_id, :author_id, NULL, '2026-08-26T11:00:00+00:00')"
            ),
            {
                "id": str(uuid4()),
                "review_id": str(seeded["review_id"]),
                "author_id": str(uuid4()),
            },
        )

    with engine.begin() as connection:
        recovered = module.TerminalReviewPackageGenerator(storage).generate(
            connection,
            event_id=seeded["event_id"],
            workflow_id=seeded["workflow_id"],
            correlation_id="restart-correlation-id",
        )

    assert recovered.created is True
    assert len(storage.objects) == 2
    assert (
        next(item.content for key, item in storage.objects.items() if key.endswith("manifest.json"))
        == original_manifest
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM review_final_packages")) == 1
        assert connection.scalar(text("SELECT COUNT(*) FROM audit_events")) == 1
    engine.dispose()


def test_production_s3_package_write_requires_kms_encryption() -> None:
    module = _final_package_module()
    requests: list[dict[str, object]] = []
    client = SimpleNamespace(put_object=lambda **request: requests.append(request))
    storage = module.S3FinalPackageStorage(
        client=client,
        bucket="documents",
        production=True,
        kms_key_id="alias/documents",
    )

    assert storage.put_immutable(
        "reviews/package.json",
        b"{}",
        content_type="application/json",
        sha256=module.sha256(b"{}").hexdigest(),
    )
    assert requests[0]["ServerSideEncryption"] == "aws:kms"
    assert requests[0]["SSEKMSKeyId"] == "alias/documents"


def test_worker_rejects_an_existing_object_with_a_different_checksum() -> None:
    """Fails if a retry silently accepts unrelated bytes at an immutable package key."""
    module = _final_package_module()
    engine, seeded = _seed_terminal_workflow()
    storage = MemoryPackageStorage()
    base = (
        f"reviews/{seeded['organization_id']}/{seeded['workspace_id']}/"
        f"{seeded['review_id']}/final-package"
    )
    storage.objects[f"{base}/manifest.json"] = SimpleNamespace(
        content=b"unrelated", content_type="application/json"
    )

    with pytest.raises(module.FinalPackageConflictError), engine.begin() as connection:
        module.TerminalReviewPackageGenerator(storage).generate(
            connection,
            event_id=seeded["event_id"],
            workflow_id=seeded["workflow_id"],
            correlation_id="conflict-correlation-id",
        )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM review_final_packages")) == 0
    engine.dispose()


def _seed_terminal_workflow() -> tuple[object, dict[str, UUID]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    review_id = uuid4()
    workflow_id = uuid4()
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    policy_version_id = uuid4()
    event_id = uuid4()
    actor_id = uuid4()
    stage_id = uuid4()
    schema = """
    CREATE TABLE review_cases (
      id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
      agreement_id TEXT NOT NULL, agreement_version_id TEXT, created_by TEXT NOT NULL
    );
    CREATE TABLE review_workflows (
      id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
      review_id TEXT NOT NULL, policy_version_id TEXT NOT NULL, state TEXT NOT NULL,
      revision INTEGER NOT NULL
    );
    CREATE TABLE review_workflow_decisions (
      id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, workflow_stage_id TEXT NOT NULL,
      actor_id TEXT NOT NULL, action TEXT NOT NULL, occurred_at TEXT NOT NULL
    );
    CREATE TABLE review_workflow_outbox (
      id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, package_snapshot TEXT
    );
    CREATE TABLE review_workflow_stages (
      id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
      state TEXT NOT NULL, activated_at TEXT, completed_at TEXT
    );
    CREATE TABLE review_assignments (
      id TEXT PRIMARY KEY, review_id TEXT NOT NULL, assignee_id TEXT NOT NULL,
      status TEXT NOT NULL, due_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE review_comments (
      id TEXT PRIMARY KEY, review_id TEXT NOT NULL, author_id TEXT NOT NULL,
      finding_id TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE playbook_evaluations (
      id TEXT PRIMARY KEY, agreement_id TEXT NOT NULL
    );
    CREATE TABLE playbook_findings (
      id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL, organization_id TEXT NOT NULL,
      workspace_id TEXT NOT NULL, result TEXT NOT NULL, severity TEXT NOT NULL,
      citation_ids TEXT NOT NULL
    );
    CREATE TABLE review_final_packages (
      id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
      review_id TEXT NOT NULL UNIQUE, workflow_id TEXT NOT NULL, state TEXT NOT NULL,
      manifest_key TEXT NOT NULL UNIQUE, pdf_key TEXT NOT NULL UNIQUE,
      manifest_checksum TEXT NOT NULL, pdf_checksum TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE audit_events (
      id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
      actor_id TEXT NOT NULL, action TEXT NOT NULL, resource_type TEXT NOT NULL,
      resource_id TEXT, outcome TEXT NOT NULL, correlation_id TEXT NOT NULL,
      before_ref TEXT NOT NULL, after_ref TEXT NOT NULL, metadata_json TEXT NOT NULL,
      occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """
    with engine.begin() as connection:
        for statement in schema.split(";"):
            if statement.strip():
                connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO review_cases VALUES "
                "(:id, :organization_id, :workspace_id, :agreement_id, NULL, :actor_id)"
            ),
            {
                "id": str(review_id),
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "agreement_id": str(agreement_id),
                "actor_id": str(actor_id),
            },
        )
        connection.execute(
            text(
                "INSERT INTO review_workflows VALUES "
                "(:id, :organization_id, :workspace_id, :review_id, :policy_version_id, "
                "'rejected', 1)"
            ),
            {
                "id": str(workflow_id),
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "review_id": str(review_id),
                "policy_version_id": str(policy_version_id),
            },
        )
        connection.execute(
            text(
                "INSERT INTO review_workflow_stages VALUES "
                "(:id, :workflow_id, 1, 'completed', '2026-08-26T10:00:00+00:00', "
                "'2026-08-26T10:01:00+00:00')"
            ),
            {"id": str(stage_id), "workflow_id": str(workflow_id)},
        )
        connection.execute(
            text(
                "INSERT INTO review_workflow_decisions VALUES "
                "(:id, :workflow_id, :stage_id, :actor_id, 'reject', "
                "'2026-08-26T10:01:00+00:00')"
            ),
            {
                "id": str(uuid4()),
                "workflow_id": str(workflow_id),
                "stage_id": str(stage_id),
                "actor_id": str(actor_id),
            },
        )
        connection.execute(
            text("INSERT INTO review_workflow_outbox VALUES (:id, :workflow_id, :snapshot)"),
            {
                "id": str(event_id),
                "workflow_id": str(workflow_id),
                "snapshot": dumps(
                    {
                        "review_id": str(review_id),
                        "agreement_id": str(agreement_id),
                        "agreement_version_id": None,
                        "workflow_id": str(workflow_id),
                        "policy_version_id": str(policy_version_id),
                        "state": "rejected",
                        "revision": 1,
                        "decisions": [
                            {
                                "action": "reject",
                                "actor_id": str(actor_id),
                                "stage_id": str(stage_id),
                                "occurred_at": "2026-08-26T10:01:00+00:00",
                            }
                        ],
                        "stages": [
                            {
                                "id": str(stage_id),
                                "ordinal": 1,
                                "state": "completed",
                                "activated_at": "2026-08-26T10:00:00+00:00",
                                "completed_at": "2026-08-26T10:01:00+00:00",
                            }
                        ],
                        "assignments": [],
                        "comments": [],
                        "findings": [],
                        "audit_event_ids": [],
                    },
                    sort_keys=True,
                ),
            },
        )
    return engine, {
        "event_id": event_id,
        "workflow_id": workflow_id,
        "review_id": review_id,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
    }
