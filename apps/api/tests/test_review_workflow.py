from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps
from uuid import uuid4

import agreement_intelligence_api.playbooks.models  # noqa: F401
import agreement_intelligence_api.processing.models  # noqa: F401
import pytest
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.approval_policies.models import (
    ApprovalPolicyRecord,
    ApprovalPolicyStageRecord,
    ApprovalPolicyVersionRecord,
)
from agreement_intelligence_api.audit.models import AuditEventRecord
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.storage import StoredDocument
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.main import app
from agreement_intelligence_api.reviews import workflow as workflow_module
from agreement_intelligence_api.reviews import workflow_routes as workflow_routes_module
from agreement_intelligence_api.reviews.models import (
    ReviewAssignmentRecord,
    ReviewCaseRecord,
    ReviewFinalPackageRecord,
    ReviewNotificationEventRecord,
    ReviewWorkflowOutboxRecord,
    ReviewWorkflowRecord,
)
from agreement_intelligence_api.reviews.workflow import (
    LoggingReviewWorkflowQueuePublisher,
    ReviewWorkflowConflictError,
    ReviewWorkflowCoordinator,
    ReviewWorkflowQueueDispatcher,
    _workflow_for_decision_update,
)
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class _RecordingStorage:
    def __init__(self, documents: dict[str, StoredDocument] | None = None) -> None:
        self.documents = documents or {}
        self.puts: list[str] = []

    def put_immutable(self, key: str, content: bytes, *, content_type: str, sha256: str) -> bool:
        self.puts.append(key)
        self.documents[key] = StoredDocument(content=content, content_type=content_type)
        return True

    def read(self, key: str) -> StoredDocument | None:
        return self.documents.get(key)

    def delete(self, key: str) -> None:
        raise AssertionError("final-package GET endpoints must never delete objects")


def _recording_refresh(
    calls: list[tuple[str, object]], original_refresh: Callable[..., None]
) -> Callable[..., None]:
    def refresh(instance: object, *args: object, **kwargs: object) -> None:
        calls.append(("refresh", instance))
        original_refresh(instance, *args, **kwargs)

    return refresh


def test_decision_processing_locks_the_workflow_before_validating_revision() -> None:
    statement = _workflow_for_decision_update(uuid4())

    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]

    assert "FOR UPDATE OF review_workflows" in sql
    assert statement.get_execution_options()["populate_existing"] is True


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
def client_for_session(session: Session) -> Generator[Callable[[object], TestClient]]:
    app.dependency_overrides[get_session] = lambda: session

    def build_client(user_id: object) -> TestClient:
        app.dependency_overrides[current_principal] = lambda: Principal(user_id=user_id)  # type: ignore[arg-type]
        return TestClient(app)

    try:
        yield build_client
    finally:
        app.dependency_overrides.clear()


def test_terminal_decision_emits_a_correlated_package_generation_event(session: Session) -> None:
    """Fails if terminal package work is not durably represented in the workflow outbox."""
    review, policy_version = _seed_review_and_published_policy(session)
    started = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="terminal-package-start",
    )

    ReviewWorkflowCoordinator(session).decide(
        workflow_id=started.id,
        actor_id=review.created_by,
        action="reject",
        idempotency_key="terminal-package-reject",
        expected_revision=started.revision,
        correlation_id="terminal-package-correlation",
    )

    event_record = session.scalar(
        select(ReviewWorkflowOutboxRecord)
        .where(ReviewWorkflowOutboxRecord.workflow_id == started.id)
        .where(ReviewWorkflowOutboxRecord.correlation_id == "terminal-package-correlation")
    )
    assert event_record is not None
    assert event_record.event_type == "review.workflow.terminal"
    assert event_record.correlation_id == "terminal-package-correlation"
    assert event_record.package_snapshot is not None
    assert event_record.package_snapshot["state"] == "rejected"


def test_unconfigured_logging_dispatcher_keeps_outbox_pending(session: Session) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="pending-without-queue",
    )
    event = session.scalar(select(ReviewWorkflowOutboxRecord))
    assert event is not None

    delivered = ReviewWorkflowQueueDispatcher(
        session, LoggingReviewWorkflowQueuePublisher()
    ).dispatch_pending(organization_id=review.organization_id, workspace_id=review.workspace_id)

    assert delivered == 0
    assert event.delivered_at is None


def test_terminal_package_metadata_get_is_read_only_while_generation_is_pending(
    session: Session,
    client_for_session: Callable[[object], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if a metadata GET creates S3 objects, package metadata, or audit rows."""
    review, policy_version = _seed_review_and_published_policy(session)
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="pending-package-start",
    )
    workflow_record = session.get(ReviewWorkflowRecord, workflow.id)
    assert workflow_record is not None
    workflow_record.state = "rejected"
    session.commit()
    storage = _RecordingStorage()
    monkeypatch.setattr(workflow_routes_module, "storage_from_environment", lambda: storage)

    response = client_for_session(review.created_by).get(
        f"/reviews/{review.id}/final-package",
        params={
            "organization_id": str(review.organization_id),
            "workspace_id": str(review.workspace_id),
        },
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "3"
    assert response.json() == {"detail": {"code": "final_package_pending", "retryable": True}}
    assert storage.puts == []
    assert session.scalar(select(func.count()).select_from(ReviewFinalPackageRecord)) == 0
    assert (
        session.scalar(
            select(func.count())
            .select_from(AuditEventRecord)
            .where(AuditEventRecord.action == "review_final_package_generated")
        )
        == 0
    )


def test_final_package_gets_report_missing_or_corrupt_objects_as_retryable_unavailable(
    session: Session,
    client_for_session: Callable[[object], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if GETs claim an immutable package is available without checksum-valid objects."""
    review, policy_version = _seed_review_and_published_policy(session)
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="unavailable-package-start",
    )
    workflow_record = session.get(ReviewWorkflowRecord, workflow.id)
    assert workflow_record is not None
    workflow_record.state = "rejected"
    manifest = dumps({"review_id": str(review.id)}).encode()
    pdf = b"%PDF-1.4\nvalid"
    package = ReviewFinalPackageRecord(
        organization_id=review.organization_id,
        workspace_id=review.workspace_id,
        review_id=review.id,
        workflow_id=workflow.id,
        state="rejected",
        manifest_key=f"reviews/{review.id}/manifest.json",
        pdf_key=f"reviews/{review.id}/report.pdf",
        manifest_checksum=sha256(manifest).hexdigest(),
        pdf_checksum=sha256(pdf).hexdigest(),
    )
    session.add(package)
    session.commit()
    storage = _RecordingStorage()
    monkeypatch.setattr(workflow_routes_module, "storage_from_environment", lambda: storage)
    client = client_for_session(review.created_by)
    params = {
        "organization_id": str(review.organization_id),
        "workspace_id": str(review.workspace_id),
    }

    metadata = client.get(f"/reviews/{review.id}/final-package", params=params)
    storage.documents.update(
        {
            package.manifest_key: StoredDocument(content=manifest, content_type="application/json"),
            package.pdf_key: StoredDocument(
                content=b"%PDF-1.4\ncorrupt", content_type="application/pdf"
            ),
        }
    )
    pdf_download = client.get(f"/reviews/{review.id}/final-package/pdf", params=params)

    for response in (metadata, pdf_download):
        assert response.status_code == 503
        assert response.headers["retry-after"] == "3"
        assert response.json() == {
            "detail": {"code": "final_package_unavailable", "retryable": True}
        }
    assert storage.puts == []


@pytest.mark.parametrize(
    "failure",
    [
        EndpointConnectionError(endpoint_url="http://storage.invalid"),
        ClientError({"Error": {"Code": "SlowDown"}}, "GetObject"),
        ClientError({"Error": {"Code": "InternalError"}}, "GetObject"),
    ],
)
def test_final_package_get_maps_operational_storage_failures_to_retryable_unavailable(
    session: Session,
    client_for_session: Callable[[object], TestClient],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="storage-failure-start",
    )
    workflow_record = session.get(ReviewWorkflowRecord, workflow.id)
    assert workflow_record is not None
    workflow_record.state = "rejected"
    session.add(
        ReviewFinalPackageRecord(
            organization_id=review.organization_id,
            workspace_id=review.workspace_id,
            review_id=review.id,
            workflow_id=workflow.id,
            state="rejected",
            manifest_key="manifest.json",
            pdf_key="report.pdf",
            manifest_checksum="0" * 64,
            pdf_checksum="0" * 64,
        )
    )
    session.commit()

    class FailingStorage(_RecordingStorage):
        def read(self, key: str) -> StoredDocument | None:
            raise failure

    monkeypatch.setattr(
        workflow_routes_module, "storage_from_environment", lambda: FailingStorage()
    )
    response = client_for_session(review.created_by).get(
        f"/reviews/{review.id}/final-package",
        params={
            "organization_id": str(review.organization_id),
            "workspace_id": str(review.workspace_id),
        },
    )
    assert response.status_code == 503
    assert response.headers["retry-after"] == "3"
    assert response.json()["detail"] == {
        "code": "final_package_unavailable",
        "retryable": True,
    }


def test_final_package_get_authorization_hides_review_without_touching_storage(
    session: Session,
    client_for_session: Callable[[object], TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="authorized-package-start",
    )
    workflow_record = session.get(ReviewWorkflowRecord, workflow.id)
    assert workflow_record is not None
    workflow_record.state = "rejected"
    session.commit()
    outsider = IdentityService(session).provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"package-outsider-{uuid4()}",
        display_name="Package outsider",
    )
    session.commit()
    storage = _RecordingStorage()
    monkeypatch.setattr(workflow_routes_module, "storage_from_environment", lambda: storage)

    response = client_for_session(outsider.id).get(
        f"/reviews/{review.id}/final-package",
        params={
            "organization_id": str(review.organization_id),
            "workspace_id": str(review.workspace_id),
        },
    )

    assert response.status_code == 404
    assert storage.puts == []


def test_starting_a_review_activates_the_first_stage_and_persists_a_resume_checkpoint(
    session: Session,
) -> None:
    """Fails if a review can start without durable stage/checkpoint state."""
    review, policy_version = _seed_review_and_published_policy(session)

    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="review-start-001",
    )

    assert workflow.state == "waiting_for_approval"
    assert workflow.active_stage_ordinal == 1
    assert workflow.checkpoint_id is not None
    assert len(workflow.stages) == 2
    assert workflow.stages[0].state == "active"
    assert workflow.stages[1].state == "pending"
    assert [event.event_type for event in workflow.pending_events] == ["review.workflow.resume"]


def test_start_restores_tenant_scope_before_refreshing_after_commit(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    calls: list[tuple[str, object]] = []
    original_refresh = session.refresh

    monkeypatch.setattr(
        workflow_module,
        "_scope_transaction",
        lambda _, organization_id: calls.append(("scope", organization_id)),
    )
    monkeypatch.setattr(session, "refresh", _recording_refresh(calls, original_refresh))

    ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="review-start-rls-refresh",
    )

    assert [kind for kind, _ in calls[-2:]] == ["scope", "refresh"]
    assert calls[-2][1] == review.organization_id


def test_decision_restores_tenant_scope_before_refreshing_after_commit(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="review-decision-rls-start",
    )
    calls: list[tuple[str, object]] = []
    original_refresh = session.refresh

    monkeypatch.setattr(
        workflow_module,
        "_scope_transaction",
        lambda _, organization_id: calls.append(("scope", organization_id)),
    )
    monkeypatch.setattr(session, "refresh", _recording_refresh(calls, original_refresh))

    ReviewWorkflowCoordinator(session).decide(
        workflow_id=workflow.id,
        actor_id=review.created_by,
        action="reject",
        idempotency_key="decision-rls-refresh",
        expected_revision=workflow.revision,
        correlation_id="review-decision-rls-refresh",
    )

    assert [kind for kind, _ in calls[-2:]] == ["scope", "refresh"]
    assert calls[-2][1] == review.organization_id


def test_stage_activation_assigns_each_eligible_actor_once(session: Session) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    coordinator = ReviewWorkflowCoordinator(session)
    coordinator.start(
        review_id=review.id, policy_version_id=policy_version.id, correlation_id="assign"
    )
    coordinator.start(
        review_id=review.id, policy_version_id=policy_version.id, correlation_id="repeat"
    )
    assignments = session.query(ReviewAssignmentRecord).filter_by(review_id=review.id).all()
    notifications = (
        session.query(ReviewNotificationEventRecord).filter_by(review_id=review.id).all()
    )
    assert len(assignments) == 1
    assert len(notifications) == 1


def test_submitter_cannot_approve_and_stage_requires_eligible_role(session: Session) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="review-start-eligibility",
    )

    with pytest.raises(ReviewWorkflowConflictError, match="submitter_cannot_approve"):
        ReviewWorkflowCoordinator(session).decide(
            workflow_id=workflow.id,
            actor_id=review.created_by,
            action="approve",
            idempotency_key="decision-submitter",
            expected_revision=workflow.revision,
            correlation_id="decision-submitter",
        )

    outsider = IdentityService(session).provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"outsider-{uuid4()}",
        display_name="Outsider",
    )
    session.commit()
    with pytest.raises(ReviewWorkflowConflictError, match="actor_not_eligible"):
        ReviewWorkflowCoordinator(session).decide(
            workflow_id=workflow.id,
            actor_id=outsider.id,
            action="approve",
            idempotency_key="decision-outsider",
            expected_revision=workflow.revision,
            correlation_id="decision-outsider",
        )


def test_stage_completion_counts_unique_eligible_actors(session: Session) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    identity = IdentityService(session)
    reviewer = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"reviewer-{uuid4()}",
        display_name="Legal reviewer",
    )
    membership = identity.grant_membership(
        organization_id=review.organization_id,
        user_id=reviewer.id,
        role_key=RoleKey.LEGAL_ADMIN,
    )
    identity.grant_workspace_membership(
        organization_id=review.organization_id,
        membership_id=membership.id,
        workspace_id=review.workspace_id,
    )
    session.commit()
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="review-start-unique",
    )
    first = ReviewWorkflowCoordinator(session).decide(
        workflow_id=workflow.id,
        actor_id=reviewer.id,
        action="approve",
        idempotency_key="decision-first",
        expected_revision=workflow.revision,
        correlation_id="decision-first",
    )
    assert first.active_stage_ordinal == 2


def test_cross_stage_same_approver_is_rejected_by_default(session: Session) -> None:
    review, policy_version = _seed_review_and_published_policy(session)
    identity = IdentityService(session)
    reviewer = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"shared-{uuid4()}",
        display_name="Shared reviewer",
    )
    legal_membership = identity.grant_membership(
        organization_id=review.organization_id,
        user_id=reviewer.id,
        role_key=RoleKey.LEGAL_ADMIN,
    )
    business_membership = identity.grant_membership(
        organization_id=review.organization_id,
        user_id=reviewer.id,
        role_key=RoleKey.BUSINESS_APPROVER,
    )
    identity.grant_workspace_membership(
        organization_id=review.organization_id,
        membership_id=legal_membership.id,
        workspace_id=review.workspace_id,
    )
    identity.grant_workspace_membership(
        organization_id=review.organization_id,
        membership_id=business_membership.id,
        workspace_id=review.workspace_id,
    )
    session.commit()
    workflow = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=policy_version.id,
        correlation_id="review-start-cross-stage",
    )
    next_stage = ReviewWorkflowCoordinator(session).decide(
        workflow_id=workflow.id,
        actor_id=reviewer.id,
        action="approve",
        idempotency_key="decision-legal",
        expected_revision=workflow.revision,
        correlation_id="decision-legal",
    )
    with pytest.raises(ReviewWorkflowConflictError, match="cross_stage_approver_not_allowed"):
        ReviewWorkflowCoordinator(session).decide(
            workflow_id=workflow.id,
            actor_id=reviewer.id,
            action="approve",
            idempotency_key="decision-business",
            expected_revision=next_stage.revision,
            correlation_id="decision-business",
        )


def _seed_review_and_published_policy(
    session: Session,
) -> tuple[ReviewCaseRecord, ApprovalPolicyVersionRecord]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    organization = identity.create_organization(name="Acme", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Commercial",
        slug=f"commercial-{uuid4()}",
    )
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"legal-admin-{uuid4()}",
        display_name="Legal admin",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.LEGAL_ADMIN,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
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
    session.flush()
    review = ReviewCaseRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement.id,
        agreement_version_id=None,
        state="open",
        created_by=user.id,
        idempotency_key="review-001",
        revision=0,
        created_at=now,
        updated_at=now,
    )
    policy = ApprovalPolicyRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Client approval",
        agreement_family="client_agreement",
        document_direction="any",
        jurisdiction="any",
        materiality="any",
        precedence=100,
        created_by=user.id,
    )
    session.add_all([review, policy])
    session.flush()
    version = ApprovalPolicyVersionRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        policy_id=policy.id,
        version=1,
        status="published",
        submitter_may_approve=False,
        allow_cross_stage_same_approver=False,
        created_by=user.id,
        published_at=now,
    )
    session.add(version)
    session.flush()
    session.add_all(
        [
            ApprovalPolicyStageRecord(
                organization_id=organization.id,
                workspace_id=workspace.id,
                policy_version_id=version.id,
                ordinal=1,
                name="Legal approval",
                approval_mode="all",
                quorum_count=None,
                eligible_role_keys=["legal_admin"],
                eligible_user_ids=[],
                deadline_hours=None,
                escalation_role_key=None,
            ),
            ApprovalPolicyStageRecord(
                organization_id=organization.id,
                workspace_id=workspace.id,
                policy_version_id=version.id,
                ordinal=2,
                name="Business approval",
                approval_mode="all",
                quorum_count=None,
                eligible_role_keys=["business_approver"],
                eligible_user_ids=[],
                deadline_hours=None,
                escalation_role_key=None,
            ),
        ]
    )
    session.commit()
    return review, version
