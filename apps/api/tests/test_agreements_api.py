from collections.abc import Callable, Generator
from datetime import UTC, datetime
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
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import fixture, raises
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as inspect_database
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

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
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
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


def test_platform_admin_can_permanently_delete_an_agreement(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_business_user_scope(session)
    payload = _agreement_payload("Disposable agreement")
    payload["files"][0]["storage_key"] = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/documents/abc/original.pdf"
    )
    agreement = client_for_session(user_id).post(
        "/agreements",
        params=_scope_query(organization, workspace),
        json=payload,
    )
    agreement_id = UUID(agreement.json()["id"])
    artifact_key = (
        f"tenants/{organization.id}/workspaces/{workspace.id}/agreements/{agreement_id}/"
        "analysis/abc/analysis.json"
    )
    job_id = uuid4()
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
    session.commit()
    admin_id = _create_platform_admin(session, organization, workspace)
    client = client_for_session(admin_id)
    deleted_keys: list[str] = []

    class Storage:
        def put_immutable(self, *args: object, **kwargs: object) -> bool:
            return True

        def read(self, key: str) -> None:
            return None

        def delete(self, key: str) -> None:
            deleted_keys.append(key)

    app.state.document_storage = Storage()

    deleted = client.delete(
        f"/agreements/{agreement_id}",
        params=_scope_query(organization, workspace),
    )

    assert deleted.status_code == 204
    assert (
        client.get(
            f"/agreements/{agreement_id}",
            params=_scope_query(organization, workspace),
        ).status_code
        == 404
    )
    assert deleted_keys == [
        f"tenants/{organization.id}/workspaces/{workspace.id}/documents/abc/original.pdf",
        artifact_key,
    ]
    from agreement_intelligence_api.agreements.models import AgreementDeletionAuditEventRecord

    audit = session.query(AgreementDeletionAuditEventRecord).one()
    assert audit.agreement_id == agreement_id
    assert audit.actor_id == admin_id
    assert audit.file_checksums == ["sha256:abc123"]
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
