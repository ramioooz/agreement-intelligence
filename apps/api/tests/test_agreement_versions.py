from collections.abc import Callable, Generator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.routes import get_document_service
from agreement_intelligence_api.documents.service import DocumentService
from agreement_intelligence_api.documents.storage import StoredDocument
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import fixture
from sqlalchemy import create_engine
from sqlalchemy import inspect as inspect_database
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class MemoryStorage:
    def __init__(self) -> None:
        self.documents: dict[str, StoredDocument] = {}

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        del sha256
        if key in self.documents:
            return False
        self.documents[key] = StoredDocument(content=content, content_type=content_type)
        return True

    def read(self, key: str) -> StoredDocument | None:
        return self.documents.get(key)

    def delete(self, key: str) -> None:
        self.documents.pop(key, None)


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
    app.dependency_overrides[get_document_service] = lambda: DocumentService(
        MemoryStorage(), max_bytes=10 * 1024 * 1024
    )

    def build_client(user_id: UUID) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
        return TestClient(app)

    try:
        yield build_client
    finally:
        app.dependency_overrides.clear()


def _create_scope(
    session: Session, *, role: RoleKey = RoleKey.BUSINESS_USER
) -> tuple[UUID, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"version-user-{uuid4()}",
        display_name="Version User",
    )
    organization = identity.create_organization(
        name=f"Version Org {uuid4()}", slug=f"version-org-{uuid4()}"
    )
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Version Workspace",
        slug=f"version-workspace-{uuid4()}",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=role,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return user.id, organization, workspace


def _scope(organization: Organization, workspace: Workspace) -> dict[str, str]:
    return {
        "organization_id": str(organization.id),
        "workspace_id": str(workspace.id),
    }


def _create_agreement(client: TestClient, scope: dict[str, str]) -> dict[str, object]:
    response = client.post(
        "/agreements",
        params=scope,
        json={
            "title": "Client terms",
            "agreement_type": "client_agreement",
            "files": [
                {
                    "file_name": "client-terms-v1.pdf",
                    "content_type": "application/pdf",
                    "storage_key": "source/client-terms-v1.pdf",
                    "checksum": "legacy-checksum-v1",
                    "byte_size": 100,
                    "version_number": 1,
                }
            ],
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_existing_agreement_file_becomes_immutable_version_one(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_scope(session)
    client = client_for_session(user_id)
    agreement = _create_agreement(client, _scope(organization, workspace))

    response = client.get(
        f"/agreements/{agreement['id']}/versions",
        params=_scope(organization, workspace),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_version_id"] == payload["items"][0]["id"]
    assert payload["comparison_baseline_version_id"] is None
    assert payload["items"] == [
        {
            "id": payload["items"][0]["id"],
            "agreement_id": agreement["id"],
            "organization_id": str(organization.id),
            "workspace_id": str(workspace.id),
            "version_number": 1,
            "predecessor_version_id": None,
            "file": {
                "file_name": "client-terms-v1.pdf",
                "content_type": "application/pdf",
                "storage_key": "source/client-terms-v1.pdf",
                "checksum": "legacy-checksum-v1",
                "byte_size": 100,
                "version_number": 1,
            },
            "uploaded_by": str(user_id),
            "uploaded_at": payload["items"][0]["uploaded_at"],
            "processing_state": "pending",
            "processing_job_id": None,
            "extraction_version": None,
            "analysis_provenance": {},
        }
    ]


def test_revision_upload_is_idempotent_and_rejects_duplicate_or_stale_lineage(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    user_id, organization, workspace = _create_scope(session)
    client = client_for_session(user_id)
    scope = _scope(organization, workspace)
    agreement = _create_agreement(client, scope)
    url = f"/agreements/{agreement['id']}/versions"
    headers = {"Idempotency-Key": "revision-upload-v2"}
    form = {**scope, "expected_current_version": "1"}
    first = client.post(
        url,
        headers=headers,
        data=form,
        files={"file": ("client-terms-v2.pdf", b"%PDF-1.4 revised terms", "application/pdf")},
    )
    repeated = client.post(
        url,
        headers=headers,
        data=form,
        files={"file": ("client-terms-v2.pdf", b"%PDF-1.4 revised terms", "application/pdf")},
    )
    duplicate = client.post(
        url,
        headers={"Idempotency-Key": "different-request"},
        data={**scope, "expected_current_version": "2"},
        files={"file": ("duplicate.pdf", b"%PDF-1.4 revised terms", "application/pdf")},
    )
    stale = client.post(
        url,
        headers={"Idempotency-Key": "stale-request"},
        data=form,
        files={"file": ("client-terms-v3.pdf", b"%PDF-1.4 third terms", "application/pdf")},
    )

    assert first.status_code == 201
    assert first.json()["version_number"] == 2
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_version"
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_current_version"


def test_read_only_reviewer_cannot_upload_a_revision(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    owner_id, organization, workspace = _create_scope(session)
    owner = client_for_session(owner_id)
    agreement = _create_agreement(owner, _scope(organization, workspace))
    identity = IdentityService(session)
    reviewer = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"reviewer-{uuid4()}",
        display_name="Reviewer",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=reviewer.id,
        role_key=RoleKey.LEGAL_REVIEWER,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()

    response = client_for_session(reviewer.id).post(
        f"/agreements/{agreement['id']}/versions",
        headers={"Idempotency-Key": "reviewer-upload"},
        data={**_scope(organization, workspace), "expected_current_version": "1"},
        files={"file": ("forbidden.pdf", b"%PDF-1.4 forbidden", "application/pdf")},
    )

    assert response.status_code == 404


def test_version_lineage_migration_creates_version_tables_and_backfills_legacy_files(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "versions.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    inspector = inspect_database(create_engine(f"sqlite+pysqlite:///{database_path}"))
    assert "agreement_versions" in inspector.get_table_names()
    assert "agreement_version_audit_events" in inspector.get_table_names()
    assert "version_id" in {column["name"] for column in inspector.get_columns("processing_jobs")}
