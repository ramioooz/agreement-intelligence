from collections.abc import Callable, Generator
from datetime import UTC, datetime
from json import dumps
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactIntentRecord,
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import MonkeyPatch, fixture, raises
from sqlalchemy import create_engine, select, text
from sqlalchemy import inspect as inspect_database
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

AUTH_CORRELATION_ID = "11111111-1111-4111-8111-111111111111"
MISSING_SCOPE_CORRELATION_ID = "22222222-2222-4222-8222-222222222222"
BAD_LIMIT_CORRELATION_ID = "33333333-3333-4333-8333-333333333333"
CROSS_WORKSPACE_CORRELATION_IDS = {
    "get": "44444444-4444-4444-8444-444444444444",
    "post_archive": "55555555-5555-4555-8555-555555555555",
    "post_restore": "66666666-6666-4666-8666-666666666666",
}
CROSS_TENANT_CORRELATION_IDS = {
    "list": "77777777-7777-4777-8777-777777777777",
    "get": "88888888-8888-4888-8888-888888888888",
    "archive": "99999999-9999-4999-8999-999999999999",
    "restore": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
}


@fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@fixture
def client_for_session(session: Session) -> Generator[Callable[[UUID], TestClient]]:
    app.dependency_overrides[get_session] = lambda: session

    def build_client(user_id: UUID) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
        return TestClient(app)

    try:
        yield build_client
    finally:
        app.dependency_overrides.clear()


def _agreement_payload(title: str, agreement_type: str = "client") -> dict[str, Any]:
    return {
        "title": title,
        "agreement_type": agreement_type,
        "status": "draft",
        "parties": [
            {"name": "Example Client Ltd", "role": "client"},
            {"name": "Example Broker Ltd", "role": "provider"},
        ],
        "files": [
            {
                "file_name": "agreement.pdf",
                "content_type": "application/pdf",
                "storage_key": "source/tenant/agreement.pdf",
                "checksum": "sha256:abc123",
                "byte_size": 1234,
                "version_number": 1,
            }
        ],
        "processing_state": "pending",
        "audit_metadata": {"source": "api"},
    }


def _scope_query(organization: Organization, workspace: Workspace) -> dict[str, str]:
    return {
        "organization_id": str(organization.id),
        "workspace_id": str(workspace.id),
    }


def _create_business_user_scope(session: Session) -> tuple[UUID, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"user-{uuid4()}",
        display_name="Business User",
    )
    organization = identity.create_organization(name=f"Acme {uuid4()}", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Derivatives",
        slug=f"derivatives-{uuid4()}",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.BUSINESS_USER,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return user.id, organization, workspace


def _create_platform_admin(
    session: Session, organization: Organization, workspace: Workspace
) -> UUID:
    identity = IdentityService(session)
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"admin-{uuid4()}",
        display_name="Platform Admin",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.PLATFORM_ADMIN,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return user.id


def test_create_agreement_persists_repository_metadata(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)

    response = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload("Client agreement"),
    )

    assert response.status_code == 201
    created = response.json()
    assert created["organization_id"] == str(organization.id)
    assert created["workspace_id"] == str(workspace.id)
    assert created["parties"] == [
        {"name": "Example Client Ltd", "role": "client"},
        {"name": "Example Broker Ltd", "role": "provider"},
    ]
    assert created["files"] == [
        {
            "file_name": "agreement.pdf",
            "content_type": "application/pdf",
            "storage_key": "source/tenant/agreement.pdf",
            "checksum": "sha256:abc123",
            "byte_size": 1234,
            "version_number": 1,
        }
    ]
    assert created["processing_state"] == "pending"
    assert created["audit_metadata"] == {"source": "api"}
    assert created["audit_events"][0]["action"] == "created"
    assert created["audit_events"][0]["actor_id"] == str(user_id)
    assert created["audit_events"][0]["occurred_at"]
    assert created["archived_at"] is None
    assert created["created_at"]
    assert created["updated_at"]

    detail = client.get(
        f"/agreements/{created['id']}",
        params=_scope_query(organization, workspace),
    )

    assert detail.status_code == 200
    assert detail.json() == created


def test_platform_admin_accepts_durable_agreement_deletion_before_storage_cleanup(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    payload = _agreement_payload("Disposable agreement")
    checksum = "a" * 64
    payload["files"][0]["storage_key"] = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/documents/{checksum}/original.pdf"
    )
    agreement = client_for_session(user_id).post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=payload,
    )
    agreement_id = UUID(agreement.json()["id"])
    artifact_key = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/agreements/{agreement_id}/"
        f"analysis/{checksum}/document-analysis.v1.json"
    )
    expected_artifact_key = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/agreements/{agreement_id}/"
        f"analysis/{'b' * 64}/document-analysis.v1.json"
    )
    job_id = uuid4()
    expected_job_id = uuid4()
    now = datetime.now(UTC)
    session.add(
        ProcessingJobRecord(
            id=job_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            idempotency_key="delete-test",
            profile="baseline",
            source_storage_key=payload["files"][0]["storage_key"],
            source_checksum="sha256:abc123",
            source_content_type="application/pdf",
            state="completed",
            attempt_count=1,
            queued_at=now,
            processing_started_at=now,
            completed_at=now,
        )
    )
    session.add(
        ProcessingArtifactRecord(
            job_id=job_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            artifact_key=artifact_key,
        )
    )
    session.add(
        ProcessingJobRecord(
            id=expected_job_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            idempotency_key="delete-expected-test",
            profile="baseline",
            source_storage_key=payload["files"][0]["storage_key"],
            source_checksum="sha256:def456",
            source_content_type="application/pdf",
            state="processing",
            attempt_count=1,
            queued_at=now,
            processing_started_at=now,
        )
    )
    session.add(
        ProcessingArtifactIntentRecord(
            job_id=expected_job_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            profile="baseline",
            category="analysis",
            artifact_key=expected_artifact_key,
        )
    )
    review_id = uuid4()
    workflow_id = uuid4()
    terminal_event_id = uuid4()
    package_base = f"reviews/{organization.id}/{workspace.id}/{review_id}/final-package"
    manifest_key = f"{package_base}/manifest.json"
    pdf_key = f"{package_base}/report.pdf"
    legacy_manifest_key = f"{package_base}/legacy-manifest.json"
    legacy_pdf_key = f"{package_base}/legacy-report.pdf"
    session.execute(
        text(
            """
            INSERT INTO review_cases (
                id, organization_id, workspace_id, agreement_id, agreement_version_id,
                state, created_by, idempotency_key, revision, created_at, updated_at
            ) VALUES (
                :id, :organization_id, :workspace_id, :agreement_id, NULL,
                'open', :created_by, 'deletion-terminal-review', 1, :now, :now
            )
            """
        ),
        {
            "id": review_id.hex,
            "organization_id": organization.id.hex,
            "workspace_id": workspace.id.hex,
            "agreement_id": agreement_id.hex,
            "created_by": user_id.hex,
            "now": now.isoformat(),
        },
    )
    session.execute(
        text(
            """
            INSERT INTO review_workflows (
                id, organization_id, workspace_id, review_id, policy_version_id,
                checkpoint_id, state, active_stage_ordinal, revision, created_at, updated_at
            ) VALUES (
                :id, :organization_id, :workspace_id, :review_id, :policy_version_id,
                :checkpoint_id, 'rejected', NULL, 1, :now, :now
            )
            """
        ),
        {
            "id": workflow_id.hex,
            "organization_id": organization.id.hex,
            "workspace_id": workspace.id.hex,
            "review_id": review_id.hex,
            "policy_version_id": uuid4().hex,
            "checkpoint_id": uuid4().hex,
            "now": now.isoformat(),
        },
    )
    session.execute(
        text(
            """
            INSERT INTO review_workflow_outbox (
                id, workflow_id, organization_id, workspace_id, event_type,
                correlation_id, idempotency_key, package_snapshot,
                package_manifest_key, package_pdf_key, delivered_at, attempt_count,
                created_at
            ) VALUES (
                :id, :workflow_id, :organization_id, :workspace_id,
                'review.workflow.terminal', 'deletion-terminal-correlation',
                'deletion-terminal-event', :package_snapshot,
                :manifest_key, :pdf_key, NULL, 0, :now
            )
            """
        ),
        {
            "id": terminal_event_id.hex,
            "workflow_id": workflow_id.hex,
            "organization_id": organization.id.hex,
            "workspace_id": workspace.id.hex,
            "package_snapshot": dumps(
                {
                    "review_id": str(review_id),
                    "legacy_manifest_key": legacy_manifest_key,
                    "legacy_pdf_key": legacy_pdf_key,
                }
            ),
            "manifest_key": manifest_key,
            "pdf_key": pdf_key,
            "now": now.isoformat(),
        },
    )
    session.commit()
    admin_id = _create_platform_admin(session, organization, workspace)
    client = client_for_session(admin_id)
    deleted_keys: list[str] = []
    read_keys: list[str] = []

    class Storage:
        def put_immutable(self, *args: object, **kwargs: object) -> bool:
            return True

        def read(self, key: str) -> None:
            read_keys.append(key)
            return None

        def delete(self, key: str) -> None:
            deleted_keys.append(key)

    app.state.document_storage = Storage()

    deleted = client.delete(
        f"/agreements/{agreement_id}",
        params=_scope_query(organization, workspace),
    )

    assert deleted.status_code == 202
    deletion = deleted.json()
    assert deletion["agreement_id"] == str(agreement_id)
    assert deletion["state"] == "accepted"
    assert (
        client.get(
            f"/agreements/{agreement_id}",
            params=_scope_query(organization, workspace),
        ).status_code
        == 404
    )
    blocked_processing = client.post(
        f"/agreements/{agreement_id}/processing-jobs",
        params=_scope_query(organization, workspace),
        headers={"Idempotency-Key": "blocked-after-delete"},
        json={"profile": "baseline"},
    )
    assert blocked_processing.status_code == 404
    blocked_comparison = client.post(
        f"/agreements/{agreement_id}/version-comparisons",
        params=_scope_query(organization, workspace),
        headers={"Idempotency-Key": "blocked-comparison-after-delete"},
        json={},
    )
    assert blocked_comparison.status_code == 404
    blocked_review = client.post(
        "/reviews",
        params=_scope_query(organization, workspace),
        json={
            "agreement_id": str(agreement_id),
            "idempotency_key": "blocked-review-after-delete",
        },
    )
    assert blocked_review.status_code == 404
    blocked_source = client.get(
        "/documents/download",
        params={
            **_scope_query(organization, workspace),
            "object_key": payload["files"][0]["storage_key"],
        },
    )
    assert blocked_source.status_code == 404
    assert read_keys == []
    assert deleted_keys == []
    from agreement_intelligence_api.agreements.models import AgreementDeletionAuditEventRecord

    audit = session.query(AgreementDeletionAuditEventRecord).one()
    assert audit.agreement_id == agreement_id
    assert audit.actor_id == admin_id
    assert audit.file_checksums == ["sha256:abc123"]
    assert audit.event_type == "requested"

    from agreement_intelligence_api.agreements.models import (
        AgreementDeletionObjectRecord,
        AgreementDeletionOutboxRecord,
        AgreementDeletionRequestRecord,
    )

    request_record = session.query(AgreementDeletionRequestRecord).one()
    assert request_record.id == UUID(deletion["id"])
    assert request_record.state == "accepted"
    inventory = (
        session.query(AgreementDeletionObjectRecord)
        .order_by(AgreementDeletionObjectRecord.category.desc())
        .all()
    )
    assert {(item.category, item.object_key) for item in inventory} == {
        ("source", payload["files"][0]["storage_key"]),
        ("analysis", artifact_key),
        ("analysis", expected_artifact_key),
        ("review_manifest", manifest_key),
        ("review_manifest", legacy_manifest_key),
        ("review_pdf", pdf_key),
        ("review_pdf", legacy_pdf_key),
    }
    outbox = session.query(AgreementDeletionOutboxRecord).one()
    assert outbox.deletion_id == request_record.id
    del app.state.document_storage


def test_deletion_inventory_covers_immutable_versions_and_preserves_shared_sources(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    from agreement_intelligence_api.agreements.models import (
        AgreementDeletionObjectRecord,
        AgreementDeletionRequestRecord,
        AgreementRecord,
        AgreementVersionRecord,
    )
    from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
    from agreement_intelligence_api.comparisons.models import VersionComparisonRunRecord
    from agreement_intelligence_api.processing.models import (
        ProcessingArtifactRecord,
        ProcessingJobRecord,
    )

    owner_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(owner_id)
    scope = _scope_query(organization, workspace)
    shared_key = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/documents/{'a' * 64}/original.pdf"
    )
    target_payload = _agreement_payload("Target")
    target_payload["files"][0]["storage_key"] = shared_key
    target = client.post("/agreements", params=scope, json=target_payload).json()

    target_id = UUID(target["id"])
    historical_key = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/documents/{'b' * 64}/original.pdf"
    )
    current_alias = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/documents/{'c' * 64}/original.pdf"
    )
    now = datetime.now(UTC)
    version_one = session.scalar(
        select(AgreementVersionRecord).where(AgreementVersionRecord.agreement_id == target_id)
    )
    assert version_one is not None
    keeper = AgreementRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        title="Keeper",
        agreement_type="client",
        status="draft",
        parties=[],
        files=[{**target_payload["files"][0], "storage_key": shared_key}],
        processing_state="pending",
        audit_metadata={},
        audit_events=[],
        created_at=now,
        updated_at=now,
    )
    session.add(keeper)
    session.flush()
    session.add(
        AgreementVersionRecord(
            agreement_id=keeper.id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            version_number=1,
            predecessor_version_id=None,
            file_name="shared.pdf",
            content_type="application/pdf",
            storage_key=shared_key,
            checksum="a" * 64,
            byte_size=10,
            uploaded_by=owner_id,
            uploaded_at=now,
            processing_state="completed",
            idempotency_key="keeper-v1",
        )
    )
    session.add(
        AgreementVersionRecord(
            agreement_id=target_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            version_number=2,
            predecessor_version_id=version_one.id,
            file_name="history.pdf",
            content_type="application/pdf",
            storage_key=historical_key,
            checksum="sha256:history",
            byte_size=20,
            uploaded_by=owner_id,
            uploaded_at=now,
            processing_state="completed",
            idempotency_key="history-v2",
        )
    )
    record = session.get(AgreementRecord, target_id)
    assert record is not None
    record.files = [{**record.files[0], "storage_key": current_alias}]
    comparison_id = uuid4()
    comparison_key = f"comparisons/{comparison_id}/version-comparison.v1.json"
    comparison_job = ProcessingJobRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=target_id,
        version_id=version_one.id,
        idempotency_key="comparison-inventory",
        profile="version-comparison",
        state="completed",
        attempt_count=1,
        queued_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    embedding_job = ProcessingJobRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=target_id,
        version_id=None,
        idempotency_key="embedding-inventory",
        profile=f"embedding-reindex:{uuid4()}",
        state="completed",
        attempt_count=1,
        queued_at=now,
        completed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add_all([comparison_job, embedding_job])
    session.flush()
    session.add_all(
        [
            ProcessingArtifactRecord(
                job_id=comparison_job.id,
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=target_id,
                artifact_key=comparison_key,
            ),
            ProcessingArtifactRecord(
                job_id=embedding_job.id,
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=target_id,
                artifact_key=f"embedding-reindex/{uuid4()}.json",
            ),
            VersionComparisonRunRecord(
                id=comparison_id,
                organization_id=organization.id,
                workspace_id=workspace.id,
                agreement_id=target_id,
                baseline_version_id=version_one.id,
                target_version_id=version_one.id,
                processing_job_id=comparison_job.id,
                idempotency_key="comparison-inventory",
                analysis_version="v1",
                state="completed",
                analysis_provenance={},
                created_at=now,
                updated_at=now,
                completed_at=now,
            ),
        ]
    )
    session.commit()

    admin_id = _create_platform_admin(session, organization, workspace)
    accepted = client_for_session(admin_id).delete(f"/agreements/{target_id}", params=scope)

    assert accepted.status_code == 202
    deletion = session.query(AgreementDeletionRequestRecord).one()
    assert deletion.state == "accepted"
    inventory = {
        (item.category, item.object_key)
        for item in session.query(AgreementDeletionObjectRecord).all()
    }
    assert ("source", shared_key) in inventory
    assert ("source", historical_key) in inventory
    assert ("source", current_alias) in inventory
    assert ("comparison", comparison_key) in inventory
    assert ("analysis", comparison_key) not in inventory
    assert not any(key.startswith("embedding-reindex/") for _, key in inventory)
    repository = SQLAlchemyAgreementRepository(session)
    assert not repository.is_object_pending_deletion(
        shared_key,
        organization_id=organization.id,
        workspace_id=workspace.id,
    )
    assert repository.is_object_pending_deletion(
        historical_key,
        organization_id=organization.id,
        workspace_id=workspace.id,
    )


def test_cross_tenant_deletion_is_denied_without_creating_an_intent(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    from agreement_intelligence_api.agreements.models import AgreementDeletionRequestRecord

    owner_id, organization, workspace = _create_business_user_scope(session)
    agreement = (
        client_for_session(owner_id)
        .post(
            "/agreements",
            params=_scope_query(organization, workspace),
            json=_agreement_payload("Tenant A"),
        )
        .json()
    )
    _other_owner, other_organization, other_workspace = _create_business_user_scope(session)
    other_admin = _create_platform_admin(session, other_organization, other_workspace)

    denied = client_for_session(other_admin).delete(
        f"/agreements/{agreement['id']}",
        params=_scope_query(other_organization, other_workspace),
    )

    assert denied.status_code == 404
    assert session.query(AgreementDeletionRequestRecord).count() == 0


def test_deletion_acceptance_persists_outbox_without_calling_external_queue(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    from agreement_intelligence_api.agreements.models import AgreementDeletionOutboxRecord

    owner_id, organization, workspace = _create_business_user_scope(session)
    agreement = (
        client_for_session(owner_id)
        .post(
            "/agreements",
            params=_scope_query(organization, workspace),
            json=_agreement_payload("Outbox"),
        )
        .json()
    )
    admin_id = _create_platform_admin(session, organization, workspace)

    accepted = client_for_session(admin_id).delete(
        f"/agreements/{agreement['id']}",
        params=_scope_query(organization, workspace),
    )
    assert accepted.status_code == 202
    outbox = session.query(AgreementDeletionOutboxRecord).one()
    assert outbox.delivered_at is None
    assert outbox.next_attempt_at is not None


def test_database_failure_does_not_publish_or_mutate_external_storage(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
    monkeypatch: MonkeyPatch,
) -> None:
    owner_id, organization, workspace = _create_business_user_scope(session)
    agreement = (
        client_for_session(owner_id)
        .post(
            "/agreements",
            params=_scope_query(organization, workspace),
            json=_agreement_payload("Commit failure"),
        )
        .json()
    )
    admin_id = _create_platform_admin(session, organization, workspace)

    deleted_keys: list[str] = []

    class Storage:
        def delete(self, key: str) -> None:
            deleted_keys.append(key)

    app.state.document_storage = Storage()

    def fail_commit() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session, "commit", fail_commit)
    try:
        with raises(RuntimeError, match="database unavailable"):
            client_for_session(admin_id).delete(
                f"/agreements/{agreement['id']}",
                params=_scope_query(organization, workspace),
            )
        assert deleted_keys == []
    finally:
        session.rollback()
        del app.state.document_storage


def test_list_scopes_results_filters_and_uses_cursor_pagination(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    other_workspace = IdentityService(session).create_workspace(
        organization_id=organization.id,
        name="Credit",
        slug=f"credit-{uuid4()}",
    )
    session.commit()
    first = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload("One", "client"),
    )
    second = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload("Two", "liquidity"),
    )
    unauthorized = client.post(
        "/agreements",
        params=_scope_query(organization, other_workspace),
        json=_agreement_payload("Other", "client"),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert unauthorized.status_code == 404

    first_page = client.get(
        "/agreements",
        params={**_scope_query(organization, workspace), "limit": "1"},
    )

    assert first_page.status_code == 200
    assert first_page.json()["items"] == [second.json()]
    assert first_page.json()["page"] == {"limit": 1, "next_cursor": "1"}

    second_page = client.get(
        "/agreements",
        params={**_scope_query(organization, workspace), "limit": "1", "cursor": "1"},
    )

    assert second_page.status_code == 200
    assert second_page.json()["items"] == [first.json()]
    assert second_page.json()["page"] == {"limit": 1, "next_cursor": None}

    filtered = client.get(
        "/agreements",
        params={**_scope_query(organization, workspace), "agreement_type": "liquidity"},
    )

    assert filtered.status_code == 200
    assert filtered.json()["items"] == [second.json()]

    searched = client.get(
        "/agreements",
        params={**_scope_query(organization, workspace), "query": "two"},
    )

    assert searched.status_code == 200
    assert searched.json()["items"] == [second.json()]


def test_cross_workspace_detail_archive_and_restore_are_hidden(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    other_workspace = IdentityService(session).create_workspace(
        organization_id=organization.id,
        name="Credit",
        slug=f"credit-{uuid4()}",
    )
    session.commit()
    client = client_for_session(user_id)
    created = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload("Private"),
    ).json()

    for label, method, url in (
        ("get", "get", f"/agreements/{created['id']}"),
        ("post_archive", "post", f"/agreements/{created['id']}/archive"),
        ("post_restore", "post", f"/agreements/{created['id']}/restore"),
    ):
        response = getattr(client, method)(
            url,
            params=_scope_query(organization, other_workspace),
            headers={"X-Correlation-ID": CROSS_WORKSPACE_CORRELATION_IDS[label]},
        )
        assert response.status_code == 404
        assert response.json() == {
            "code": "agreement_not_found",
            "message": "Agreement not found",
            "correlation_id": CROSS_WORKSPACE_CORRELATION_IDS[label],
        }


def test_cross_tenant_agreement_operations_are_non_disclosing(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    outsider_id, _outsider_organization, _outsider_workspace = _create_business_user_scope(session)
    owner_id, owner_organization, owner_workspace = _create_business_user_scope(session)
    owner_client = client_for_session(owner_id)
    created = owner_client.post(
        "/agreements",
        params=_scope_query(owner_organization, owner_workspace),
        json=_agreement_payload("Tenant secret"),
    )
    assert created.status_code == 201

    outsider_client = client_for_session(outsider_id)
    requests = (
        (
            "list",
            "get",
            "/agreements",
        ),
        (
            "get",
            "get",
            f"/agreements/{created.json()['id']}",
        ),
        (
            "archive",
            "post",
            f"/agreements/{created.json()['id']}/archive",
        ),
        (
            "restore",
            "post",
            f"/agreements/{created.json()['id']}/restore",
        ),
    )

    for operation, method, url in requests:
        response = getattr(outsider_client, method)(
            url,
            params=_scope_query(owner_organization, owner_workspace),
            headers={"X-Correlation-ID": CROSS_TENANT_CORRELATION_IDS[operation]},
        )

        assert response.status_code == 404
        assert response.json() == {
            "code": "agreement_not_found",
            "message": "Agreement not found",
            "correlation_id": CROSS_TENANT_CORRELATION_IDS[operation],
        }


def test_archive_is_recoverable_and_retains_source_file_metadata(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    client = client_for_session(user_id)
    created = client.post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=_agreement_payload("Recoverable agreement"),
    ).json()

    archived = client.post(
        f"/agreements/{created['id']}/archive",
        params=_scope_query(organization, workspace),
    )

    assert archived.status_code == 200
    assert archived.json()["archived_at"]
    assert archived.json()["files"] == created["files"]
    assert archived.json()["audit_events"][-1]["action"] == "archived"
    assert archived.json()["audit_events"][-1]["actor_id"] == str(user_id)
    assert (
        client.get("/agreements", params=_scope_query(organization, workspace)).json()["items"]
        == []
    )

    restored = client.post(
        f"/agreements/{created['id']}/restore",
        params=_scope_query(organization, workspace),
    )

    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert restored.json()["files"] == created["files"]
    assert restored.json()["audit_events"][-1]["action"] == "restored"
    assert restored.json()["audit_events"][-1]["actor_id"] == str(user_id)
    assert client.get("/agreements", params=_scope_query(organization, workspace)).json()[
        "items"
    ] == [restored.json()]


def test_agreements_persist_across_database_sessions(tmp_path: Path) -> None:
    database_path = tmp_path / "agreements.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    first_session = session_factory()
    user_id, organization, workspace = _create_business_user_scope(first_session)
    organization_id = organization.id
    workspace_id = workspace.id
    app.dependency_overrides[get_session] = lambda: first_session
    app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
    try:
        created = TestClient(app).post(
            "/agreements",
            params=_scope_query(organization, workspace),
            json=_agreement_payload("Durable"),
        )
        assert created.status_code == 201
        agreement_id = created.json()["id"]
    finally:
        app.dependency_overrides.clear()
        first_session.close()

    second_session = session_factory()
    app.dependency_overrides[get_session] = lambda: second_session
    app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
    try:
        detail = TestClient(app).get(
            f"/agreements/{agreement_id}",
            params={"organization_id": str(organization_id), "workspace_id": str(workspace_id)},
        )
    finally:
        app.dependency_overrides.clear()
        second_session.close()
        engine.dispose()

    assert detail.status_code == 200
    assert detail.json()["title"] == "Durable"


def test_missing_auth_and_invalid_scope_errors_include_stable_correlation_ids(
    session: Session,
) -> None:
    _user_id, organization, workspace = _create_business_user_scope(session)
    app.dependency_overrides[get_session] = lambda: session
    try:
        missing_auth = TestClient(app).get(
            "/agreements",
            params=_scope_query(organization, workspace),
            headers={"X-Correlation-ID": AUTH_CORRELATION_ID},
        )
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=_user_id)
        missing_scope = TestClient(app).get(
            "/agreements",
            params={"organization_id": str(organization.id)},
            headers={"X-Correlation-ID": MISSING_SCOPE_CORRELATION_ID},
        )
        invalid_limit = TestClient(app).get(
            "/agreements",
            params={**_scope_query(organization, workspace), "limit": "0"},
            headers={"X-Correlation-ID": BAD_LIMIT_CORRELATION_ID},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_auth.status_code == 401
    assert missing_auth.json() == {
        "code": "authentication_required",
        "message": "Authentication required",
        "correlation_id": AUTH_CORRELATION_ID,
    }
    assert missing_scope.status_code == 422
    assert missing_scope.json() == {
        "code": "validation_error",
        "message": "Request validation failed",
        "correlation_id": MISSING_SCOPE_CORRELATION_ID,
    }
    assert invalid_limit.status_code == 422
    assert invalid_limit.json() == {
        "code": "validation_error",
        "message": "Request validation failed",
        "correlation_id": BAD_LIMIT_CORRELATION_ID,
    }


def test_agreement_migration_creates_repository_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "agreement-migration.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    table_names = inspect_database(
        create_engine(f"sqlite+pysqlite:///{database_path}")
    ).get_table_names()
    assert "agreements" in table_names
    assert "document_object_registry" in table_names


def test_retrieval_index_build_migration_rejects_an_agreement_from_another_scope(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "retrieval-index-scope.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")
    command.upgrade(config, "head")

    organization_a, organization_b = uuid4().hex, uuid4().hex
    workspace_a, workspace_b = uuid4().hex, uuid4().hex
    agreement_a = uuid4().hex
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys = ON"))
            connection.execute(
                text(
                    """
                    INSERT INTO organizations (id, name, slug) VALUES
                    (:organization_a, 'Organization A', 'organization-a'),
                    (:organization_b, 'Organization B', 'organization-b')
                    """
                ),
                {"organization_a": organization_a, "organization_b": organization_b},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO workspaces (id, organization_id, name, slug) VALUES
                    (:workspace_a, :organization_a, 'Workspace A', 'workspace-a'),
                    (:workspace_b, :organization_b, 'Workspace B', 'workspace-b')
                    """
                ),
                {
                    "workspace_a": workspace_a,
                    "organization_a": organization_a,
                    "workspace_b": workspace_b,
                    "organization_b": organization_b,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO agreements (
                        id, organization_id, workspace_id, title, agreement_type, status,
                        parties, files, processing_state, audit_metadata, audit_events
                    ) VALUES (
                        :agreement_a, :organization_a, :workspace_a, 'Agreement A', 'client',
                        'draft', '[]', '[]', 'queued', '{}', '[]'
                    )
                    """
                ),
                {
                    "agreement_a": agreement_a,
                    "organization_a": organization_a,
                    "workspace_a": workspace_a,
                },
            )

            with raises(IntegrityError):
                connection.execute(
                    text(
                        """
                        INSERT INTO retrieval_index_builds (
                            id, organization_id, workspace_id, agreement_id, source_checksum,
                            chunker_version, state
                        ) VALUES (
                            :build_id, :organization_b, :workspace_b, :agreement_a,
                            :source_checksum, 'structure-aware.v1', 'building'
                        )
                        """
                    ),
                    {
                        "build_id": uuid4().hex,
                        "organization_b": organization_b,
                        "workspace_b": workspace_b,
                        "agreement_a": agreement_a,
                        "source_checksum": "a" * 64,
                    },
                )
    finally:
        engine.dispose()
