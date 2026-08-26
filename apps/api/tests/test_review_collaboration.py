from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.audit.models import AuditEventRecord
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.reviews.models import ReviewAssignmentRecord, ReviewCommentRecord
from agreement_intelligence_api.reviews.workflow import (
    ReviewWorkflowCoordinator,
    ReviewWorkflowQueueDispatcher,
)
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


@pytest.fixture
def client_for_session(session: Session) -> Generator[Callable[[UUID], TestClient]]:
    app.dependency_overrides[get_session] = lambda: session

    def build_client(user_id: UUID) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)
        return TestClient(app)

    try:
        yield build_client
    finally:
        app.dependency_overrides.clear()


def test_deletion_tombstone_blocks_existing_review_reads_and_mutations(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_scope(session)
    client = client_for_session(seeded.assigner_id)
    started = client.post(
        "/reviews",
        params=seeded.scope,
        json={
            "agreement_id": str(seeded.agreement_id),
            "idempotency_key": "review-before-deletion",
        },
    )
    assert started.status_code == 201
    agreement = session.get(AgreementRecord, seeded.agreement_id)
    assert agreement is not None
    agreement.deletion_requested_at = datetime.now(UTC)
    session.commit()

    blocked_read = client.get(f"/reviews/{started.json()['id']}", params=seeded.scope)
    blocked_comment = client.post(
        f"/reviews/{started.json()['id']}/comments",
        params=seeded.scope,
        json={"body": "must not persist", "idempotency_key": "after-delete"},
    )

    assert blocked_read.status_code == 404
    assert blocked_comment.status_code == 404
    assert session.query(ReviewCommentRecord).count() == 0


def test_review_assignment_reassignment_and_comment_are_workspace_scoped_and_idempotent(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_scope(session)
    assigner = client_for_session(seeded.assigner_id)
    due_at = (datetime.now(UTC) + timedelta(days=3)).isoformat()

    started = assigner.post(
        "/reviews",
        params=seeded.scope,
        json={
            "agreement_id": str(seeded.agreement_id),
            "idempotency_key": "review-001",
        },
    )
    assert started.status_code == 201
    review_id = started.json()["id"]

    assigned = assigner.post(
        f"/reviews/{review_id}/assignments",
        params=seeded.scope,
        json={
            "assignee_id": str(seeded.reviewer_id),
            "due_at": due_at,
            "idempotency_key": "assignment-001",
        },
    )
    duplicate_assignment = assigner.post(
        f"/reviews/{review_id}/assignments",
        params=seeded.scope,
        json={
            "assignee_id": str(seeded.reviewer_id),
            "due_at": due_at,
            "idempotency_key": "assignment-001",
        },
    )
    assert assigned.status_code == 201
    assert duplicate_assignment.status_code == 200
    assignment = assigned.json()
    assert duplicate_assignment.json()["id"] == assignment["id"]

    reviewer = client_for_session(seeded.reviewer_id)
    inbox = reviewer.get("/reviews/inbox", params=seeded.scope)
    assert inbox.status_code == 200
    assert [item["id"] for item in inbox.json()] == [assignment["id"]]

    assigner = client_for_session(seeded.assigner_id)
    reassigned = assigner.post(
        f"/reviews/{review_id}/assignments/{assignment['id']}/reassign",
        params=seeded.scope,
        json={
            "assignee_id": str(seeded.replacement_id),
            "due_at": due_at,
            "expected_revision": 0,
            "idempotency_key": "reassignment-001",
        },
    )
    assert reassigned.status_code == 201
    assert reassigned.json()["predecessor_assignment_id"] == assignment["id"]
    original_assignment = session.get(ReviewAssignmentRecord, UUID(assignment["id"]))
    assert original_assignment is not None
    assert original_assignment.status == "reassigned"

    stale_reassignment = assigner.post(
        f"/reviews/{review_id}/assignments/{assignment['id']}/reassign",
        params=seeded.scope,
        json={
            "assignee_id": str(seeded.replacement_id),
            "due_at": due_at,
            "expected_revision": 0,
            "idempotency_key": "reassignment-stale",
        },
    )
    assert stale_reassignment.status_code == 409

    commented = reviewer.post(
        f"/reviews/{review_id}/comments",
        params=seeded.scope,
        json={
            "body": "The liability cap needs legal review.",
            "idempotency_key": "comment-001",
        },
    )
    duplicate_comment = reviewer.post(
        f"/reviews/{review_id}/comments",
        params=seeded.scope,
        json={
            "body": "The liability cap needs legal review.",
            "idempotency_key": "comment-001",
        },
    )
    assert commented.status_code == 201
    assert duplicate_comment.status_code == 200
    assert session.query(ReviewCommentRecord).count() == 1

    replacement_inbox = client_for_session(seeded.replacement_id).get(
        "/reviews/inbox", params=seeded.scope
    )
    assert replacement_inbox.status_code == 200
    assert replacement_inbox.json()[0]["review_id"] == review_id


def test_review_comment_timeline_and_notification_indicator_are_visible_only_to_the_recipient(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_scope(session)
    assigner = client_for_session(seeded.assigner_id)
    started = assigner.post(
        "/reviews",
        params=seeded.scope,
        json={"agreement_id": str(seeded.agreement_id), "idempotency_key": "review-timeline"},
    )
    review_id = started.json()["id"]
    assigned = assigner.post(
        f"/reviews/{review_id}/assignments",
        params=seeded.scope,
        json={"assignee_id": str(seeded.reviewer_id), "idempotency_key": "assignment-timeline"},
    )
    assert assigned.status_code == 201

    reviewer = client_for_session(seeded.reviewer_id)
    commented = reviewer.post(
        f"/reviews/{review_id}/comments",
        params=seeded.scope,
        json={"body": "Please confirm the liability cap.", "idempotency_key": "comment-timeline"},
    )
    assert commented.status_code == 201

    timeline = reviewer.get(f"/reviews/{review_id}/comments", params=seeded.scope)
    notifications = reviewer.get("/reviews/notifications", params=seeded.scope)

    assert timeline.status_code == 200
    assert [item["body"] for item in timeline.json()] == ["Please confirm the liability cap."]
    assert notifications.status_code == 200
    assert notifications.json()["unread_count"] == 1

    unrelated = client_for_session(seeded.replacement_id)
    assert unrelated.get("/reviews/notifications", params=seeded.scope).json()["unread_count"] == 0


def test_business_approver_can_read_inbox(
    session: Session, client_for_session: Callable[[UUID], TestClient]
) -> None:
    seeded = _seed_scope(session)
    identity = IdentityService(session)
    approver = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"approver-{uuid4()}",
        display_name="Approver",
    )
    membership = identity.grant_membership(
        organization_id=seeded.organization_id,
        user_id=approver.id,
        role_key=RoleKey.BUSINESS_APPROVER,
    )
    identity.grant_workspace_membership(
        organization_id=seeded.organization_id,
        membership_id=membership.id,
        workspace_id=seeded.workspace_id,
    )
    session.commit()
    assigner = client_for_session(seeded.assigner_id)
    review = assigner.post(
        "/reviews",
        params=seeded.scope,
        json={"agreement_id": str(seeded.agreement_id), "idempotency_key": "business-inbox"},
    ).json()
    assigned = assigner.post(
        f"/reviews/{review['id']}/assignments",
        params=seeded.scope,
        json={"assignee_id": str(approver.id), "idempotency_key": "business-assignment"},
    )
    assert assigned.status_code == 201
    inbox = client_for_session(approver.id).get("/reviews/inbox", params=seeded.scope)
    assert inbox.status_code == 200
    assert inbox.json()[0]["assignee_id"] == str(approver.id)


def test_review_start_reapplies_tenant_scope_after_creation_commit(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed_scope(session)
    scoped_organizations: list[UUID] = []
    original_scope_organization = IdentityService.scope_organization

    def track_scope(service: IdentityService, organization_id: UUID) -> None:
        scoped_organizations.append(organization_id)
        original_scope_organization(service, organization_id)

    monkeypatch.setattr(IdentityService, "scope_organization", track_scope)

    response = client_for_session(seeded.assigner_id).post(
        "/reviews",
        params=seeded.scope,
        json={
            "agreement_id": str(seeded.agreement_id),
            "idempotency_key": "review-tenant-scope",
        },
    )

    assert response.status_code == 201
    assert scoped_organizations == [seeded.organization_id]


def test_policy_override_persists_only_the_structured_reason_code(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed_scope(session)
    monkeypatch.setattr(ReviewWorkflowCoordinator, "start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ReviewWorkflowQueueDispatcher,
        "dispatch_pending",
        lambda _self, **_kwargs: 0,
    )

    response = client_for_session(seeded.assigner_id).post(
        "/reviews",
        params=seeded.scope,
        json={
            "agreement_id": str(seeded.agreement_id),
            "idempotency_key": "review-policy-override",
            "policy_version_id": str(uuid4()),
            "policy_override_reason_code": "risk_exception",
        },
    )

    assert response.status_code == 201
    audit_event = session.scalar(
        select(AuditEventRecord).where(AuditEventRecord.action == "review_policy_override")
    )
    assert audit_event is not None
    assert audit_event.metadata_json == {"reason_code": "risk_exception"}


def test_policy_override_uses_other_code_for_legacy_reason_without_auditing_it(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed_scope(session)
    monkeypatch.setattr(ReviewWorkflowCoordinator, "start", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ReviewWorkflowQueueDispatcher,
        "dispatch_pending",
        lambda _self, **_kwargs: 0,
    )

    response = client_for_session(seeded.assigner_id).post(
        "/reviews",
        params=seeded.scope,
        json={
            "agreement_id": str(seeded.agreement_id),
            "idempotency_key": "review-legacy-policy-override",
            "policy_version_id": str(uuid4()),
            "policy_override_reason": "Contact legal@example.test about sk-proj-demo-secret.",
        },
    )

    assert response.status_code == 201
    audit_event = session.scalar(
        select(AuditEventRecord).where(AuditEventRecord.action == "review_policy_override")
    )
    assert audit_event is not None
    assert audit_event.metadata_json == {"reason_code": "other"}


def test_policy_override_rejects_unsupported_note_input(
    session: Session,
    client_for_session: Callable[[UUID], TestClient],
) -> None:
    seeded = _seed_scope(session)

    response = client_for_session(seeded.assigner_id).post(
        "/reviews",
        params=seeded.scope,
        json={
            "agreement_id": str(seeded.agreement_id),
            "idempotency_key": "review-policy-note",
            "policy_override_note": "Contact legal@example.test about sk-proj-demo-secret.",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "policy_override_note_not_supported"}
    assert session.scalar(select(AuditEventRecord.id)) is None


def test_notification_migration_adds_worker_processing_marker(tmp_path: Path) -> None:
    database_path = tmp_path / "review-notifications.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    columns = {
        column["name"]
        for column in inspect(create_engine(f"sqlite+pysqlite:///{database_path}")).get_columns(
            "review_notification_events"
        )
    }
    assert "processed_at" in columns


class _Scope:
    def __init__(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        assigner_id: UUID,
        reviewer_id: UUID,
        replacement_id: UUID,
    ) -> None:
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.agreement_id = agreement_id
        self.assigner_id = assigner_id
        self.reviewer_id = reviewer_id
        self.replacement_id = replacement_id

    @property
    def scope(self) -> dict[str, str]:
        return {
            "organization_id": str(self.organization_id),
            "workspace_id": str(self.workspace_id),
        }


def _seed_scope(session: Session) -> _Scope:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    organization = identity.create_organization(name="Acme", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Commercial",
        slug=f"commercial-{uuid4()}",
    )
    users = []
    for subject, role in (
        ("assigner", RoleKey.LEGAL_ADMIN),
        ("reviewer", RoleKey.LEGAL_REVIEWER),
        ("replacement", RoleKey.LEGAL_REVIEWER),
    ):
        user = identity.provision_user(
            issuer="https://identity.example/realms/demo",
            subject=f"{subject}-{uuid4()}",
            display_name=subject.title(),
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
        users.append(user)
    now = datetime.now(UTC)
    agreement = AgreementRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        title="Client agreement",
        agreement_type="client_agreement",
        status="draft",
        parties=[],
        files=[],
        processing_state="completed",
        audit_metadata={},
        audit_events=[],
        created_at=now,
        updated_at=now,
    )
    session.add(agreement)
    session.commit()
    return _Scope(
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement.id,
        assigner_id=users[0].id,
        reviewer_id=users[1].id,
        replacement_id=users[2].id,
    )
