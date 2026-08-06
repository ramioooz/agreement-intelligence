from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
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
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.models import (
    ReviewAssignmentRecord,
    ReviewCaseRecord,
    ReviewNotificationEventRecord,
)
from agreement_intelligence_api.reviews.workflow import (
    ReviewWorkflowConflictError,
    ReviewWorkflowCoordinator,
)
from sqlalchemy import create_engine, event
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
