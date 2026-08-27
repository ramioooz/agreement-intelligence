from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.access import active_agreement_statement
from agreement_intelligence_api.agreements.models import AgreementRecord, AgreementVersionRecord
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.models import Membership, WorkspaceMembership
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.collaboration_schemas import (
    CreateAssignmentRequest,
    CreateReviewCommentRequest,
    ReassignAssignmentRequest,
    ReviewAssignmentResponse,
    ReviewCaseResponse,
    ReviewCommentResponse,
    ReviewNotificationSummaryResponse,
    StartReviewRequest,
)
from agreement_intelligence_api.reviews.models import (
    PlaybookFindingRecord,
    ReviewAssignmentRecord,
    ReviewCaseRecord,
    ReviewCommentRecord,
    ReviewNotificationEventRecord,
)


class ReviewConflictError(Exception):
    pass


class ReviewCollaborationService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def start(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        request: StartReviewRequest,
    ) -> tuple[ReviewCaseResponse, bool]:
        self._authorize_assign(principal, organization_id, workspace_id)
        self._agreement(request.agreement_id, organization_id, workspace_id)
        self._version(
            request.agreement_version_id, request.agreement_id, organization_id, workspace_id
        )
        existing = self._session.scalar(
            select(ReviewCaseRecord)
            .where(ReviewCaseRecord.agreement_id == request.agreement_id)
            .where(ReviewCaseRecord.agreement_version_id == request.agreement_version_id)
            .where(ReviewCaseRecord.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if (
                existing.agreement_id != request.agreement_id
                or existing.agreement_version_id != request.agreement_version_id
            ):
                raise ReviewConflictError
            return self._review_response(existing), False
        now = datetime.now(UTC)
        record = ReviewCaseRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=request.agreement_id,
            agreement_version_id=request.agreement_version_id,
            state="open",
            created_by=principal.user_id,
            idempotency_key=request.idempotency_key,
            revision=0,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        try:
            self._session.commit()
            self._identity.scope_organization(organization_id)
        except IntegrityError as error:
            self._session.rollback()
            existing = self._session.scalar(
                select(ReviewCaseRecord)
                .where(ReviewCaseRecord.agreement_id == request.agreement_id)
                .where(ReviewCaseRecord.agreement_version_id == request.agreement_version_id)
                .where(ReviewCaseRecord.idempotency_key == request.idempotency_key)
            )
            if existing is None:
                raise error
            return self._review_response(existing), False
        return self._review_response(record), True

    def get(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID, review_id: UUID
    ) -> ReviewCaseResponse:
        self._authorize_read(principal, organization_id, workspace_id)
        return self._review_response(
            self._review(review_id, organization_id, workspace_id, for_update=False)
        )

    def inbox(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> list[ReviewAssignmentResponse]:
        can_decide = self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.REVIEWS_DECIDE,
        )
        can_approve = self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.REVIEWS_APPROVE,
        )
        if not (can_decide or can_approve):
            hide_resource()
        assignments = self._session.scalars(
            select(ReviewAssignmentRecord)
            .join(ReviewCaseRecord, ReviewAssignmentRecord.review_id == ReviewCaseRecord.id)
            .join(AgreementRecord, ReviewCaseRecord.agreement_id == AgreementRecord.id)
            .where(ReviewAssignmentRecord.organization_id == organization_id)
            .where(ReviewAssignmentRecord.workspace_id == workspace_id)
            .where(ReviewAssignmentRecord.assignee_id == principal.user_id)
            .where(ReviewAssignmentRecord.status == "active")
            .where(AgreementRecord.deletion_requested_at.is_(None))
            .order_by(ReviewAssignmentRecord.due_at, ReviewAssignmentRecord.created_at)
        )
        return [self._assignment_response(item) for item in assignments]

    def comments(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID, review_id: UUID
    ) -> list[ReviewCommentResponse]:
        self._authorize_read(principal, organization_id, workspace_id)
        self._review(review_id, organization_id, workspace_id, for_update=False)
        records = self._session.scalars(
            select(ReviewCommentRecord)
            .where(ReviewCommentRecord.organization_id == organization_id)
            .where(ReviewCommentRecord.workspace_id == workspace_id)
            .where(ReviewCommentRecord.review_id == review_id)
            .order_by(ReviewCommentRecord.created_at, ReviewCommentRecord.id)
        )
        return [self._comment_response(record) for record in records]

    def notification_summary(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> ReviewNotificationSummaryResponse:
        self._authorize_read(principal, organization_id, workspace_id)
        unread_count = self._session.scalar(
            select(func.count())
            .select_from(ReviewNotificationEventRecord)
            .join(ReviewCaseRecord, ReviewNotificationEventRecord.review_id == ReviewCaseRecord.id)
            .join(AgreementRecord, ReviewCaseRecord.agreement_id == AgreementRecord.id)
            .where(ReviewNotificationEventRecord.organization_id == organization_id)
            .where(ReviewNotificationEventRecord.workspace_id == workspace_id)
            .where(ReviewNotificationEventRecord.recipient_id == principal.user_id)
            .where(ReviewNotificationEventRecord.delivered_at.is_(None))
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )
        return ReviewNotificationSummaryResponse(unread_count=unread_count or 0)

    def assign(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        review_id: UUID,
        request: CreateAssignmentRequest,
    ) -> tuple[ReviewAssignmentResponse, bool]:
        self._authorize_assign(principal, organization_id, workspace_id)
        review = self._review(review_id, organization_id, workspace_id)
        self._assignee_in_workspace(request.assignee_id, organization_id, workspace_id)
        existing = self._assignment_by_key(review.id, request.idempotency_key)
        if existing is not None:
            if existing.assignee_id != request.assignee_id or not _same_due_at(
                existing.due_at, request.due_at
            ):
                raise ReviewConflictError
            return self._assignment_response(existing), False
        now = datetime.now(UTC)
        record = ReviewAssignmentRecord(
            id=uuid4(),
            review_id=review.id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            assignee_id=request.assignee_id,
            assigned_by=principal.user_id,
            predecessor_assignment_id=None,
            due_at=request.due_at,
            status="active",
            idempotency_key=request.idempotency_key,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._notify(
            review,
            recipient_id=request.assignee_id,
            event_type="review.assignment.created",
            idempotency_key=f"assignment:{record.id}",
        )
        self._session.commit()
        return self._assignment_response(record), True

    def transfer(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        review_id: UUID,
        assignment_id: UUID,
        request: ReassignAssignmentRequest,
        kind: str,
    ) -> tuple[ReviewAssignmentResponse, bool]:
        self._authorize_assign(principal, organization_id, workspace_id)
        review = self._review(review_id, organization_id, workspace_id)
        old = self._session.scalar(
            select(ReviewAssignmentRecord)
            .where(ReviewAssignmentRecord.id == assignment_id)
            .where(ReviewAssignmentRecord.review_id == review.id)
            .where(ReviewAssignmentRecord.organization_id == organization_id)
            .where(ReviewAssignmentRecord.workspace_id == workspace_id)
        )
        if old is None:
            hide_resource()
        existing = self._assignment_by_key(review.id, request.idempotency_key)
        if existing is not None:
            if existing.assignee_id != request.assignee_id or not _same_due_at(
                existing.due_at, request.due_at
            ):
                raise ReviewConflictError
            return self._assignment_response(existing), False
        if review.revision != request.expected_revision or old.status != "active":
            raise ReviewConflictError
        self._assignee_in_workspace(request.assignee_id, organization_id, workspace_id)
        now = datetime.now(UTC)
        revision_updated = cast(
            CursorResult[object],
            self._session.execute(
                update(ReviewCaseRecord)
                .where(ReviewCaseRecord.id == review.id)
                .where(ReviewCaseRecord.revision == request.expected_revision)
                .values(revision=ReviewCaseRecord.revision + 1, updated_at=now)
            ),
        )
        if revision_updated.rowcount != 1:
            raise ReviewConflictError
        old.status = "delegated" if kind == "delegate" else "reassigned"
        old.updated_at = now
        review.revision = request.expected_revision + 1
        review.updated_at = now
        record = ReviewAssignmentRecord(
            id=uuid4(),
            review_id=review.id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            assignee_id=request.assignee_id,
            assigned_by=principal.user_id,
            predecessor_assignment_id=old.id,
            due_at=request.due_at,
            status="active",
            idempotency_key=request.idempotency_key,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._notify(
            review,
            recipient_id=request.assignee_id,
            event_type="review.assignment.delegated"
            if kind == "delegate"
            else "review.assignment.reassigned",
            idempotency_key=f"assignment:{record.id}",
        )
        self._session.commit()
        return self._assignment_response(record), True

    def comment(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        review_id: UUID,
        request: CreateReviewCommentRequest,
    ) -> tuple[ReviewCommentResponse, bool]:
        self._authorize_read(principal, organization_id, workspace_id)
        review = self._review(review_id, organization_id, workspace_id)
        self._finding(request.finding_id, organization_id, workspace_id)
        self._version(
            request.agreement_version_id, review.agreement_id, organization_id, workspace_id
        )
        if (
            request.agreement_version_id is not None
            and review.agreement_version_id is not None
            and request.agreement_version_id != review.agreement_version_id
        ):
            raise ReviewConflictError
        existing = self._session.scalar(
            select(ReviewCommentRecord)
            .where(ReviewCommentRecord.review_id == review.id)
            .where(ReviewCommentRecord.idempotency_key == request.idempotency_key)
        )
        if existing is not None:
            if (
                existing.body != request.body
                or existing.finding_id != request.finding_id
                or existing.agreement_version_id
                != (request.agreement_version_id or review.agreement_version_id)
            ):
                raise ReviewConflictError
            return self._comment_response(existing), False
        now = datetime.now(UTC)
        record = ReviewCommentRecord(
            id=uuid4(),
            review_id=review.id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            finding_id=request.finding_id,
            agreement_version_id=request.agreement_version_id or review.agreement_version_id,
            author_id=principal.user_id,
            body=request.body,
            idempotency_key=request.idempotency_key,
            created_at=now,
        )
        self._session.add(record)
        if review.created_by != principal.user_id:
            self._notify(
                review,
                recipient_id=review.created_by,
                event_type="review.comment.created",
                idempotency_key=f"comment:{record.id}:owner",
            )
        self._session.commit()
        self._identity.scope_organization(organization_id)
        return self._comment_response(record), True

    def _authorize_assign(
        self, principal: Principal, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.REVIEWS_ASSIGN,
        ):
            hide_resource()

    def _authorize_read(
        self, principal: Principal, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_READ,
        ):
            hide_resource()

    def _review(
        self,
        review_id: UUID,
        organization_id: UUID,
        workspace_id: UUID,
        *,
        for_update: bool = True,
    ) -> ReviewCaseRecord:
        statement = (
            select(ReviewCaseRecord)
            .join(AgreementRecord, ReviewCaseRecord.agreement_id == AgreementRecord.id)
            .where(ReviewCaseRecord.id == review_id)
            .where(ReviewCaseRecord.organization_id == organization_id)
            .where(ReviewCaseRecord.workspace_id == workspace_id)
            .where(AgreementRecord.deletion_requested_at.is_(None))
        )
        if for_update:
            statement = statement.with_for_update()
        record = self._session.scalar(statement)
        if record is None:
            hide_resource()
        return record

    def _agreement(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> AgreementRecord:
        record = self._session.scalar(
            active_agreement_statement(
                agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                for_update=True,
            )
        )
        if record is None:
            hide_resource()
        return record

    def _version(
        self, version_id: UUID | None, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> AgreementVersionRecord | None:
        if version_id is None:
            return None
        record = self._session.scalar(
            select(AgreementVersionRecord)
            .where(AgreementVersionRecord.id == version_id)
            .where(AgreementVersionRecord.agreement_id == agreement_id)
            .where(AgreementVersionRecord.organization_id == organization_id)
            .where(AgreementVersionRecord.workspace_id == workspace_id)
        )
        if record is None:
            hide_resource()
        return record

    def _finding(self, finding_id: UUID | None, organization_id: UUID, workspace_id: UUID) -> None:
        if finding_id is None:
            return
        record = self._session.scalar(
            select(PlaybookFindingRecord)
            .where(PlaybookFindingRecord.id == finding_id)
            .where(PlaybookFindingRecord.organization_id == organization_id)
            .where(PlaybookFindingRecord.workspace_id == workspace_id)
        )
        if record is None:
            hide_resource()

    def _assignee_in_workspace(
        self, user_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> None:
        found = self._session.scalar(
            select(WorkspaceMembership.id)
            .join(Membership, WorkspaceMembership.membership_id == Membership.id)
            .where(WorkspaceMembership.organization_id == organization_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(Membership.user_id == user_id)
        )
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="assignee_not_in_workspace"
            )

    def _assignment_by_key(
        self, review_id: UUID, idempotency_key: str
    ) -> ReviewAssignmentRecord | None:
        return self._session.scalar(
            select(ReviewAssignmentRecord)
            .where(ReviewAssignmentRecord.review_id == review_id)
            .where(ReviewAssignmentRecord.idempotency_key == idempotency_key)
        )

    def _notify(
        self,
        review: ReviewCaseRecord,
        *,
        recipient_id: UUID,
        event_type: str,
        idempotency_key: str,
    ) -> None:
        self._session.add(
            ReviewNotificationEventRecord(
                id=uuid4(),
                organization_id=review.organization_id,
                workspace_id=review.workspace_id,
                review_id=review.id,
                recipient_id=recipient_id,
                event_type=event_type,
                payload_json={"agreement_id": str(review.agreement_id)},
                idempotency_key=idempotency_key,
                delivered_at=None,
                created_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _review_response(record: ReviewCaseRecord) -> ReviewCaseResponse:
        return ReviewCaseResponse(
            id=record.id,
            agreement_id=record.agreement_id,
            agreement_version_id=record.agreement_version_id,
            state=record.state,
            created_by=record.created_by,
            revision=record.revision,
            created_at=record.created_at,
        )

    @staticmethod
    def _assignment_response(record: ReviewAssignmentRecord) -> ReviewAssignmentResponse:
        return ReviewAssignmentResponse(
            id=record.id,
            review_id=record.review_id,
            assignee_id=record.assignee_id,
            assigned_by=record.assigned_by,
            predecessor_assignment_id=record.predecessor_assignment_id,
            due_at=record.due_at,
            status=record.status,
            created_at=record.created_at,
        )

    @staticmethod
    def _comment_response(record: ReviewCommentRecord) -> ReviewCommentResponse:
        return ReviewCommentResponse(
            id=record.id,
            review_id=record.review_id,
            finding_id=record.finding_id,
            agreement_version_id=record.agreement_version_id,
            author_id=record.author_id,
            body=record.body,
            created_at=record.created_at,
        )


def _same_due_at(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return left.replace(tzinfo=left.tzinfo or UTC) == right.replace(tzinfo=right.tzinfo or UTC)
