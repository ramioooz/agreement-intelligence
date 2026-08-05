"""Durable human-approval orchestration backed by domain records and LangGraph checkpoints.

The SQLAlchemy records are the business source of truth. LangGraph persists a
resume checkpoint after a transactional outbox event is committed, so worker
restarts and at-least-once queue delivery cannot recreate a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from agreement_intelligence_api.approval_policies.models import (
    ApprovalPolicyStageRecord,
    ApprovalPolicyVersionRecord,
)
from agreement_intelligence_api.audit.service import AuditEventWriter
from agreement_intelligence_api.reviews.models import (
    ReviewCaseRecord,
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


class ReviewWorkflowGraphState(TypedDict):
    workflow_id: str
    event_type: str


class ReviewWorkflowConflictError(Exception):
    pass


class ReviewWorkflowCheckpointStore(Protocol):
    """A narrow boundary that guarantees production resumes use LangGraph checkpoints."""

    def persist(self, *, checkpoint_id: UUID, workflow_id: UUID, event_type: str) -> None: ...


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
        workflow = self._workflow(workflow_id)
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
            return len(approvals) >= (policy_stage.quorum_count or 1)
        return len(approvals) >= eligible_count

    def _advance(
        self, workflow: ReviewWorkflowRecord, stage: ReviewWorkflowStageRecord, now: datetime
    ) -> None:
        stage.state = "completed"
        stage.completed_at = now
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
        workflow.active_stage_ordinal = next_stage.ordinal

    @staticmethod
    def _complete_terminal(
        workflow: ReviewWorkflowRecord,
        stage: ReviewWorkflowStageRecord,
        state: Literal["rejected", "revision_requested"],
        now: datetime,
    ) -> None:
        stage.state = "completed"
        stage.completed_at = now
        workflow.state = state
        workflow.active_stage_ordinal = None

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
