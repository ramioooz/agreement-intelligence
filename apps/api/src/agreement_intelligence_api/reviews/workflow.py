"""Durable human-approval orchestration backed by domain records and LangGraph checkpoints.

The SQLAlchemy records are the business source of truth. LangGraph persists a
resume checkpoint after a transactional outbox event is committed, so worker
restarts and at-least-once queue delivery cannot recreate a decision.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, TypedDict
from uuid import UUID, uuid4

import boto3
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import Select

from agreement_intelligence_api.approval_policies.models import (
    ApprovalPolicyStageRecord,
    ApprovalPolicyVersionRecord,
)
from agreement_intelligence_api.audit.service import AuditEventWriter
from agreement_intelligence_api.identity.models import Membership, WorkspaceMembership
from agreement_intelligence_api.reviews.models import (
    ReviewAssignmentRecord,
    ReviewCaseRecord,
    ReviewNotificationEventRecord,
    ReviewWorkflowDecisionRecord,
    ReviewWorkflowOutboxRecord,
    ReviewWorkflowRecord,
    ReviewWorkflowStageRecord,
)

WorkflowState = Literal[
    "waiting_for_approval",
    "approved",
    "rejected",
    "revision_requested",
]
WorkflowAction = Literal["approve", "reject", "request_changes"]
logger = logging.getLogger("agreement_intelligence.api")


class ReviewWorkflowGraphState(TypedDict):
    workflow_id: str
    event_type: str


class ReviewWorkflowConflictError(Exception):
    pass


class ReviewWorkflowCheckpointStore(Protocol):
    """A narrow boundary that guarantees production resumes use LangGraph checkpoints."""

    def persist(self, *, checkpoint_id: UUID, workflow_id: UUID, event_type: str) -> None: ...


class ReviewWorkflowQueuePublisher(Protocol):
    def publish(self, event: ReviewWorkflowOutboxRecord) -> None: ...


class LoggingReviewWorkflowQueuePublisher:
    def publish(self, event: ReviewWorkflowOutboxRecord) -> None:
        logger.info(
            "review workflow queued",
            extra={"event": event.event_type, "workflow_event_id": str(event.id)},
        )


class SQSReviewWorkflowQueuePublisher:
    def __init__(self, *, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def publish(self, event: ReviewWorkflowOutboxRecord) -> None:
        request: dict[str, object] = {
            "QueueUrl": self._queue_url,
            "MessageBody": json.dumps(
                {"kind": "review-workflow", "event_id": str(event.id)}, sort_keys=True
            ),
        }
        if self._queue_url.rsplit("/", 1)[-1].endswith(".fifo"):
            request["MessageGroupId"] = str(event.workflow_id)
            request["MessageDeduplicationId"] = event.idempotency_key
        self._client.send_message(**request)


@dataclass(frozen=True)
class WorkflowStageSnapshot:
    ordinal: int
    state: str


@dataclass(frozen=True)
class WorkflowEventSnapshot:
    event_type: str


@dataclass(frozen=True)
class WorkflowSnapshot:
    id: UUID
    state: WorkflowState
    active_stage_ordinal: int | None
    checkpoint_id: UUID
    revision: int
    stages: tuple[WorkflowStageSnapshot, ...]
    pending_events: tuple[WorkflowEventSnapshot, ...]


def _workflow_for_decision_update(
    workflow_id: UUID,
) -> Select[tuple[ReviewWorkflowRecord]]:
    return (
        select(ReviewWorkflowRecord)
        .options(
            selectinload(ReviewWorkflowRecord.stages),
            selectinload(ReviewWorkflowRecord.outbox_events),
        )
        .where(ReviewWorkflowRecord.id == workflow_id)
        .with_for_update(of=ReviewWorkflowRecord)
    )


class ReviewWorkflowCoordinator:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._audit = AuditEventWriter(session)

    def start(
        self,
        *,
        review_id: UUID,
        policy_version_id: UUID,
        correlation_id: str,
    ) -> WorkflowSnapshot:
        review = self._review(review_id)
        policy_version = self._policy_version(policy_version_id, review)
        existing = self._session.scalar(
            select(ReviewWorkflowRecord)
            .options(
                selectinload(ReviewWorkflowRecord.stages),
                selectinload(ReviewWorkflowRecord.outbox_events),
            )
            .where(ReviewWorkflowRecord.review_id == review.id)
        )
        if existing is not None:
            if existing.policy_version_id != policy_version.id:
                raise ReviewWorkflowConflictError
            return self._snapshot(existing)

        policy_stages = list(
            self._session.scalars(
                select(ApprovalPolicyStageRecord)
                .where(ApprovalPolicyStageRecord.policy_version_id == policy_version.id)
                .order_by(ApprovalPolicyStageRecord.ordinal)
            )
        )
        if not policy_stages:
            raise ReviewWorkflowConflictError

        now = datetime.now(UTC)
        workflow = ReviewWorkflowRecord(
            id=uuid4(),
            organization_id=review.organization_id,
            workspace_id=review.workspace_id,
            review_id=review.id,
            policy_version_id=policy_version.id,
            checkpoint_id=uuid4(),
            state="waiting_for_approval",
            active_stage_ordinal=policy_stages[0].ordinal,
            revision=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(workflow)
        self._session.flush()
        for policy_stage in policy_stages:
            activated = policy_stage.ordinal == workflow.active_stage_ordinal
            self._session.add(
                ReviewWorkflowStageRecord(
                    id=uuid4(),
                    workflow_id=workflow.id,
                    organization_id=workflow.organization_id,
                    workspace_id=workflow.workspace_id,
                    policy_stage_id=policy_stage.id,
                    ordinal=policy_stage.ordinal,
                    state="active" if activated else "pending",
                    deadline_at=(
                        now + timedelta(hours=policy_stage.deadline_hours)
                        if activated and policy_stage.deadline_hours is not None
                        else None
                    ),
                    activated_at=now if activated else None,
                    completed_at=None,
                    escalated_at=None,
                )
            )
            if activated:
                self._activate_assignments(review, workflow, policy_stage, now)
        self._emit(
            workflow,
            event_type="review.workflow.resume",
            correlation_id=correlation_id,
            idempotency_key=f"workflow:{workflow.id}:start",
        )
        self._audit.record(
            organization_id=workflow.organization_id,
            workspace_id=workflow.workspace_id,
            actor_id=review.created_by,
            action="review_workflow_started",
            resource_type="review_workflow",
            resource_id=workflow.id,
            outcome="accepted",
            correlation_id=correlation_id,
            before_ref={"state": "not_started"},
            after_ref={"state": workflow.state, "checkpoint_id": str(workflow.checkpoint_id)},
            metadata={"review_id": str(review.id), "policy_version_id": str(policy_version.id)},
            occurred_at=now,
        )
        self._session.commit()
        self._session.refresh(workflow)
        return self._snapshot(workflow)

    def decide(
        self,
        *,
        workflow_id: UUID,
        actor_id: UUID,
        action: WorkflowAction,
        idempotency_key: str,
        expected_revision: int,
        correlation_id: str,
    ) -> WorkflowSnapshot:
        workflow = self._session.scalar(_workflow_for_decision_update(workflow_id))
        if workflow is None:
            raise ReviewWorkflowConflictError
        existing = self._session.scalar(
            select(ReviewWorkflowDecisionRecord)
            .where(ReviewWorkflowDecisionRecord.workflow_id == workflow.id)
            .where(ReviewWorkflowDecisionRecord.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.actor_id != actor_id or existing.action != action:
                raise ReviewWorkflowConflictError
            return self._snapshot(workflow)
        if workflow.revision != expected_revision or workflow.state != "waiting_for_approval":
            raise ReviewWorkflowConflictError
        stage = self._active_stage(workflow)
        policy_version = self._session.get(ApprovalPolicyVersionRecord, workflow.policy_version_id)
        if policy_version is None:
            raise ReviewWorkflowConflictError("policy_not_found")
        review = self._review(workflow.review_id)
        if (
            action == "approve"
            and not policy_version.submitter_may_approve
            and actor_id == review.created_by
        ):
            raise ReviewWorkflowConflictError("submitter_cannot_approve")
        policy_stage = self._session.get(ApprovalPolicyStageRecord, stage.policy_stage_id)
        if policy_stage is None or not self._actor_is_eligible(actor_id, workflow, policy_stage):
            raise ReviewWorkflowConflictError("actor_not_eligible")
        if action == "approve" and not policy_version.allow_cross_stage_same_approver:
            prior_approval = self._session.scalar(
                select(ReviewWorkflowDecisionRecord.id)
                .where(ReviewWorkflowDecisionRecord.workflow_id == workflow.id)
                .where(ReviewWorkflowDecisionRecord.actor_id == actor_id)
                .where(ReviewWorkflowDecisionRecord.action == "approve")
                .where(ReviewWorkflowDecisionRecord.workflow_stage_id != stage.id)
            )
            if prior_approval is not None:
                raise ReviewWorkflowConflictError("cross_stage_approver_not_allowed")
        now = datetime.now(UTC)
        self._session.add(
            ReviewWorkflowDecisionRecord(
                id=uuid4(),
                workflow_id=workflow.id,
                workflow_stage_id=stage.id,
                organization_id=workflow.organization_id,
                workspace_id=workflow.workspace_id,
                actor_id=actor_id,
                action=action,
                idempotency_key=idempotency_key,
                occurred_at=now,
            )
        )
        if action == "reject":
            self._complete_terminal(workflow, stage, "rejected", now)
        elif action == "request_changes":
            self._complete_terminal(workflow, stage, "revision_requested", now)
        elif self._stage_is_satisfied(workflow, stage):
            self._advance(workflow, stage, now)
        workflow.revision += 1
        workflow.updated_at = now
        self._emit(
            workflow,
            event_type="review.workflow.resume",
            correlation_id=correlation_id,
            idempotency_key=f"workflow:{workflow.id}:decision:{idempotency_key}",
        )
        self._audit.record(
            organization_id=workflow.organization_id,
            workspace_id=workflow.workspace_id,
            actor_id=actor_id,
            action=f"review_workflow_{action}",
            resource_type="review_workflow",
            resource_id=workflow.id,
            outcome="accepted",
            correlation_id=correlation_id,
            before_ref={"state": "waiting_for_approval", "stage": stage.ordinal},
            after_ref={"state": workflow.state, "stage": workflow.active_stage_ordinal},
            metadata={},
            occurred_at=now,
        )
        self._session.commit()
        self._session.refresh(workflow)
        return self._snapshot(workflow)

    def _review(self, review_id: UUID) -> ReviewCaseRecord:
        review = self._session.get(ReviewCaseRecord, review_id)
        if review is None:
            raise ReviewWorkflowConflictError
        return review

    def _policy_version(
        self, policy_version_id: UUID, review: ReviewCaseRecord
    ) -> ApprovalPolicyVersionRecord:
        policy_version = self._session.scalar(
            select(ApprovalPolicyVersionRecord)
            .where(ApprovalPolicyVersionRecord.id == policy_version_id)
            .where(ApprovalPolicyVersionRecord.organization_id == review.organization_id)
            .where(ApprovalPolicyVersionRecord.workspace_id == review.workspace_id)
            .where(ApprovalPolicyVersionRecord.status == "published")
        )
        if policy_version is None:
            raise ReviewWorkflowConflictError
        return policy_version

    def _workflow(self, workflow_id: UUID) -> ReviewWorkflowRecord:
        workflow = self._session.scalar(
            select(ReviewWorkflowRecord)
            .options(
                selectinload(ReviewWorkflowRecord.stages),
                selectinload(ReviewWorkflowRecord.outbox_events),
            )
            .where(ReviewWorkflowRecord.id == workflow_id)
        )
        if workflow is None:
            raise ReviewWorkflowConflictError
        return workflow

    @staticmethod
    def _active_stage(workflow: ReviewWorkflowRecord) -> ReviewWorkflowStageRecord:
        active = next((stage for stage in workflow.stages if stage.state == "active"), None)
        if active is None:
            raise ReviewWorkflowConflictError
        return active

    def _stage_is_satisfied(
        self, workflow: ReviewWorkflowRecord, stage: ReviewWorkflowStageRecord
    ) -> bool:
        policy_stage = self._session.get(ApprovalPolicyStageRecord, stage.policy_stage_id)
        if policy_stage is None:
            raise ReviewWorkflowConflictError
        approvals = self._session.scalars(
            select(ReviewWorkflowDecisionRecord)
            .where(ReviewWorkflowDecisionRecord.workflow_id == workflow.id)
            .where(ReviewWorkflowDecisionRecord.workflow_stage_id == stage.id)
            .where(ReviewWorkflowDecisionRecord.action == "approve")
        ).all()
        if policy_stage.approval_mode == "any":
            return bool(approvals)
        eligible_count = len(set(policy_stage.eligible_role_keys)) + len(
            set(policy_stage.eligible_user_ids)
        )
        if policy_stage.approval_mode == "quorum":
            return len({item.actor_id for item in approvals}) >= (policy_stage.quorum_count or 1)
        return len({item.actor_id for item in approvals}) >= eligible_count

    def _actor_is_eligible(
        self,
        actor_id: UUID,
        workflow: ReviewWorkflowRecord,
        policy_stage: ApprovalPolicyStageRecord,
    ) -> bool:
        if str(actor_id) in {str(value) for value in policy_stage.eligible_user_ids}:
            return True
        memberships = self._session.scalars(
            select(Membership)
            .join(Membership.role)
            .join(
                WorkspaceMembership,
                WorkspaceMembership.membership_id == Membership.id,
            )
            .where(Membership.organization_id == workflow.organization_id)
            .where(Membership.user_id == actor_id)
            .where(WorkspaceMembership.workspace_id == workflow.workspace_id)
        )
        eligible_roles = {str(value) for value in policy_stage.eligible_role_keys}
        return any(str(membership.role.key) in eligible_roles for membership in memberships)

    def escalate_overdue(self, *, now: datetime, correlation_id: str) -> int:
        """Mark overdue active stages once and emit an idempotent wake-up event."""
        count = 0
        workflows = self._session.scalars(
            select(ReviewWorkflowRecord)
            .options(selectinload(ReviewWorkflowRecord.stages))
            .where(ReviewWorkflowRecord.state == "waiting_for_approval")
        ).all()
        for workflow in workflows:
            stage = next((item for item in workflow.stages if item.state == "active"), None)
            if stage is None or stage.deadline_at is None or stage.deadline_at > now:
                continue
            if stage.escalated_at is not None:
                continue
            stage.escalated_at = now
            self._emit(
                workflow,
                event_type="review.workflow.escalate",
                correlation_id=correlation_id,
                idempotency_key=f"workflow:{workflow.id}:stage:{stage.ordinal}:escalation",
            )
            review = self._session.get(ReviewCaseRecord, workflow.review_id)
            self._audit.record(
                organization_id=workflow.organization_id,
                workspace_id=workflow.workspace_id,
                actor_id=review.created_by if review is not None else UUID(int=0),
                action="review_workflow_escalated",
                resource_type="review_workflow_stage",
                resource_id=stage.id,
                outcome="accepted",
                correlation_id=correlation_id,
                before_ref={"escalated_at": None},
                after_ref={"escalated_at": now.isoformat()},
                metadata={"workflow_id": str(workflow.id), "stage": stage.ordinal},
                occurred_at=now,
            )
            count += 1
        if count:
            self._session.commit()
        return count

    def _advance(
        self, workflow: ReviewWorkflowRecord, stage: ReviewWorkflowStageRecord, now: datetime
    ) -> None:
        stage.state = "completed"
        stage.completed_at = now
        self._complete_assignments(workflow, stage)
        next_stage = next(
            (candidate for candidate in workflow.stages if candidate.ordinal == stage.ordinal + 1),
            None,
        )
        if next_stage is None:
            workflow.state = "approved"
            workflow.active_stage_ordinal = None
            return
        next_stage.state = "active"
        next_stage.activated_at = now
        policy_stage = self._session.get(ApprovalPolicyStageRecord, next_stage.policy_stage_id)
        if policy_stage is not None and policy_stage.deadline_hours is not None:
            next_stage.deadline_at = now + timedelta(hours=policy_stage.deadline_hours)
        if policy_stage is not None:
            review = self._review(workflow.review_id)
            self._activate_assignments(review, workflow, policy_stage, now)
        workflow.active_stage_ordinal = next_stage.ordinal

    def _complete_terminal(
        self,
        workflow: ReviewWorkflowRecord,
        stage: ReviewWorkflowStageRecord,
        state: Literal["rejected", "revision_requested"],
        now: datetime,
    ) -> None:
        stage.state = "completed"
        stage.completed_at = now
        # Terminal decisions close any remaining active assignee work.
        for assignment in self._session.scalars(
            select(ReviewAssignmentRecord).where(
                ReviewAssignmentRecord.review_id == workflow.review_id,
                ReviewAssignmentRecord.status == "active",
            )
        ):
            assignment.status = "completed"
        workflow.state = state
        workflow.active_stage_ordinal = None

    def _eligible_actor_ids(
        self, workflow: ReviewWorkflowRecord, policy_stage: ApprovalPolicyStageRecord
    ) -> set[UUID]:
        ids = {UUID(str(value)) for value in policy_stage.eligible_user_ids}
        eligible_roles = {str(value) for value in policy_stage.eligible_role_keys}
        if eligible_roles:
            memberships = self._session.scalars(
                select(Membership)
                .join(Membership.role)
                .join(WorkspaceMembership, WorkspaceMembership.membership_id == Membership.id)
                .where(
                    Membership.organization_id == workflow.organization_id,
                    WorkspaceMembership.workspace_id == workflow.workspace_id,
                )
            )
            ids.update(
                membership.user_id
                for membership in memberships
                if str(membership.role.key) in eligible_roles
            )
        return ids

    def _activate_assignments(
        self,
        review: ReviewCaseRecord,
        workflow: ReviewWorkflowRecord,
        policy_stage: ApprovalPolicyStageRecord,
        now: datetime,
    ) -> None:
        eligible_ids = self._eligible_actor_ids(workflow, policy_stage)
        due_at = (
            now + timedelta(hours=policy_stage.deadline_hours)
            if policy_stage.deadline_hours is not None
            else None
        )
        for assignee_id in sorted(eligible_ids, key=str):
            key = f"workflow:{workflow.id}:stage:{policy_stage.ordinal}:assignee:{assignee_id}"
            existing = self._session.scalar(
                select(ReviewAssignmentRecord).where(
                    ReviewAssignmentRecord.review_id == review.id,
                    ReviewAssignmentRecord.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.status != "active":
                    existing.status = "active"
                continue
            assignment = ReviewAssignmentRecord(
                id=uuid4(),
                review_id=review.id,
                organization_id=workflow.organization_id,
                workspace_id=workflow.workspace_id,
                assignee_id=assignee_id,
                assigned_by=review.created_by,
                predecessor_assignment_id=None,
                due_at=due_at,
                status="active",
                idempotency_key=key,
                created_at=now,
                updated_at=now,
            )
            self._session.add(assignment)
            self._session.add(
                ReviewNotificationEventRecord(
                    id=uuid4(),
                    organization_id=workflow.organization_id,
                    workspace_id=workflow.workspace_id,
                    review_id=review.id,
                    recipient_id=assignee_id,
                    event_type="review.assignment.created",
                    payload_json={
                        "agreement_id": str(review.agreement_id),
                        "stage": policy_stage.ordinal,
                    },
                    idempotency_key=f"notification:{key}",
                    delivered_at=None,
                    processed_at=None,
                    created_at=now,
                )
            )

    def _complete_assignments(
        self, workflow: ReviewWorkflowRecord, stage: ReviewWorkflowStageRecord
    ) -> None:
        prefix = f"workflow:{workflow.id}:stage:{stage.ordinal}:"
        for assignment in self._session.scalars(
            select(ReviewAssignmentRecord).where(
                ReviewAssignmentRecord.review_id == workflow.review_id,
                ReviewAssignmentRecord.status == "active",
            )
        ):
            if assignment.idempotency_key.startswith(prefix):
                assignment.status = "completed"

    def _emit(
        self,
        workflow: ReviewWorkflowRecord,
        *,
        event_type: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> None:
        self._session.add(
            ReviewWorkflowOutboxRecord(
                id=uuid4(),
                workflow_id=workflow.id,
                organization_id=workflow.organization_id,
                workspace_id=workflow.workspace_id,
                event_type=event_type,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                delivered_at=None,
                created_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _snapshot(workflow: ReviewWorkflowRecord) -> WorkflowSnapshot:
        return WorkflowSnapshot(
            id=workflow.id,
            state=workflow.state,  # type: ignore[arg-type]
            active_stage_ordinal=workflow.active_stage_ordinal,
            checkpoint_id=workflow.checkpoint_id,
            revision=workflow.revision,
            stages=tuple(
                WorkflowStageSnapshot(ordinal=stage.ordinal, state=stage.state)
                for stage in workflow.stages
            ),
            pending_events=tuple(
                WorkflowEventSnapshot(event_type=event.event_type)
                for event in workflow.outbox_events
                if event.delivered_at is None
            ),
        )


class PostgresLangGraphCheckpointStore:
    """Persist resumable orchestration state with the official PostgreSQL checkpointer."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def persist(self, *, checkpoint_id: UUID, workflow_id: UUID, event_type: str) -> None:
        graph = StateGraph(ReviewWorkflowGraphState)
        graph.add_node("checkpoint", lambda state: state)
        graph.add_edge(START, "checkpoint")
        with PostgresSaver.from_conn_string(self._database_url) as checkpointer:
            checkpointer.setup()
            graph.compile(checkpointer=checkpointer).invoke(
                {
                    "workflow_id": str(workflow_id),
                    "event_type": event_type,
                },
                config={"configurable": {"thread_id": str(checkpoint_id)}},
            )


class ReviewWorkflowOutboxDispatcher:
    """Moves committed workflow wake-ups into LangGraph checkpoints exactly once."""

    def __init__(self, session: Session, checkpointer: ReviewWorkflowCheckpointStore) -> None:
        self._session = session
        self._checkpointer = checkpointer

    def dispatch_pending(self, *, limit: int = 50) -> int:
        events = self._session.scalars(
            select(ReviewWorkflowOutboxRecord)
            .join(ReviewWorkflowOutboxRecord.workflow)
            .where(ReviewWorkflowOutboxRecord.delivered_at.is_(None))
            .order_by(ReviewWorkflowOutboxRecord.created_at, ReviewWorkflowOutboxRecord.id)
            .limit(limit)
        ).all()
        delivered = 0
        for event in events:
            workflow = event.workflow
            try:
                self._checkpointer.persist(
                    checkpoint_id=workflow.checkpoint_id,
                    workflow_id=workflow.id,
                    event_type=event.event_type,
                )
            except Exception:
                self._session.rollback()
                break
            event.delivered_at = datetime.now(UTC)
            self._session.commit()
            delivered += 1
        return delivered


class ReviewWorkflowQueueDispatcher:
    """Publishes committed wake-up events; workers own checkpoint persistence."""

    def __init__(self, session: Session, publisher: ReviewWorkflowQueuePublisher) -> None:
        self._session = session
        self._publisher = publisher

    def dispatch_pending(self, *, limit: int = 50) -> int:
        events = self._session.scalars(
            select(ReviewWorkflowOutboxRecord)
            .where(ReviewWorkflowOutboxRecord.delivered_at.is_(None))
            .order_by(ReviewWorkflowOutboxRecord.created_at, ReviewWorkflowOutboxRecord.id)
            .limit(limit)
        ).all()
        delivered = 0
        for event in events:
            try:
                self._publisher.publish(event)
            except Exception:
                self._session.rollback()
                break
            event.delivered_at = datetime.now(UTC)
            self._session.commit()
            delivered += 1
        return delivered


def workflow_queue_publisher_from_environment() -> ReviewWorkflowQueuePublisher:
    queue_url = os.environ.get("SQS_NOTIFICATION_QUEUE")
    region = os.environ.get("AWS_REGION")
    if not queue_url or not region:
        return LoggingReviewWorkflowQueuePublisher()
    client = boto3.client(
        "sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"), region_name=region
    )
    if "://" not in queue_url:
        queue_url = str(client.get_queue_url(QueueName=queue_url)["QueueUrl"])
    return SQSReviewWorkflowQueuePublisher(client=client, queue_url=queue_url)
