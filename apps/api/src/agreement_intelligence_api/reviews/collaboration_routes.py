from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.approval_policies.schemas import (
    ApprovalPolicyRouteRequest,
    SupportedAgreementFamily,
)
from agreement_intelligence_api.approval_policies.service import ApprovalPolicyService
from agreement_intelligence_api.audit.service import AuditEventWriter
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.collaboration import ReviewCollaborationService
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
from agreement_intelligence_api.reviews.workflow import (
    ReviewWorkflowCoordinator,
    ReviewWorkflowQueueDispatcher,
    workflow_queue_publisher_from_environment,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


def get_collaboration_service(session: SessionDependency) -> ReviewCollaborationService:
    return ReviewCollaborationService(session, IdentityService(session))


ServiceDependency = Annotated[ReviewCollaborationService, Depends(get_collaboration_service)]


@router.post("", response_model=ReviewCaseResponse, status_code=201)
def start_review(
    request: StartReviewRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    session: SessionDependency,
    response: Response,
) -> ReviewCaseResponse:
    if request.policy_version_id is not None and not request.policy_override_reason:
        raise HTTPException(status_code=400, detail="policy_override_reason_required")
    review, created = service.start(
        principal, organization_id=organization_id, workspace_id=workspace_id, request=request
    )
    if created:
        identity = IdentityService(session)
        identity.scope_organization(organization_id)
        agreement = session.scalar(
            select(AgreementRecord).where(
                AgreementRecord.id == review.agreement_id,
                AgreementRecord.organization_id == organization_id,
                AgreementRecord.workspace_id == workspace_id,
            )
        )
        selected_policy_id = request.policy_version_id
        if (
            selected_policy_id is None
            and agreement is not None
            and agreement.agreement_type in {"client_agreement", "liquidity_provider_agreement"}
        ):
            routed = ApprovalPolicyService(session, identity).route(
                principal,
                organization_id=organization_id,
                workspace_id=workspace_id,
                request=ApprovalPolicyRouteRequest(
                    agreement_family=cast(
                        SupportedAgreementFamily,
                        agreement.agreement_type,
                    )
                ),
            )
            selected_policy_id = routed.id if routed is not None else None
        if selected_policy_id is not None:
            ReviewWorkflowCoordinator(session).start(
                review_id=review.id,
                policy_version_id=selected_policy_id,
                correlation_id="review-start",
            )
            if request.policy_version_id is not None:
                AuditEventWriter(session).record(
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    actor_id=principal.user_id,
                    action="review_policy_override",
                    resource_type="review",
                    resource_id=review.id,
                    outcome="accepted",
                    correlation_id="review-policy-override",
                    before_ref={},
                    after_ref={"policy_version_id": str(selected_policy_id)},
                    metadata={"reason": request.policy_override_reason},
                )
            ReviewWorkflowQueueDispatcher(
                session, workflow_queue_publisher_from_environment()
            ).dispatch_pending(organization_id=organization_id, workspace_id=workspace_id)
    if not created:
        response.status_code = 200
    return review


@router.get("/inbox", response_model=list[ReviewAssignmentResponse])
def review_inbox(
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> list[ReviewAssignmentResponse]:
    return service.inbox(principal, organization_id=organization_id, workspace_id=workspace_id)


@router.get("/notifications", response_model=ReviewNotificationSummaryResponse)
def review_notification_summary(
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewNotificationSummaryResponse:
    return service.notification_summary(
        principal, organization_id=organization_id, workspace_id=workspace_id
    )


@router.get("/{review_id}", response_model=ReviewCaseResponse)
def get_review(
    review_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewCaseResponse:
    return service.get(
        principal, organization_id=organization_id, workspace_id=workspace_id, review_id=review_id
    )


@router.get("/{review_id}/comments", response_model=list[ReviewCommentResponse])
def list_review_comments(
    review_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> list[ReviewCommentResponse]:
    return service.comments(
        principal, organization_id=organization_id, workspace_id=workspace_id, review_id=review_id
    )


@router.post("/{review_id}/assignments", response_model=ReviewAssignmentResponse, status_code=201)
def assign_review(
    review_id: UUID,
    request: CreateAssignmentRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    response: Response,
) -> ReviewAssignmentResponse:
    assignment, created = service.assign(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        review_id=review_id,
        request=request,
    )
    if not created:
        response.status_code = 200
    return assignment


@router.post(
    "/{review_id}/assignments/{assignment_id}/reassign",
    response_model=ReviewAssignmentResponse,
    status_code=201,
)
def reassign_review(
    review_id: UUID,
    assignment_id: UUID,
    request: ReassignAssignmentRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    response: Response,
) -> ReviewAssignmentResponse:
    assignment, created = service.transfer(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        review_id=review_id,
        assignment_id=assignment_id,
        request=request,
        kind="reassign",
    )
    if not created:
        response.status_code = 200
    return assignment


@router.post(
    "/{review_id}/assignments/{assignment_id}/delegate",
    response_model=ReviewAssignmentResponse,
    status_code=201,
)
def delegate_review(
    review_id: UUID,
    assignment_id: UUID,
    request: ReassignAssignmentRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    response: Response,
) -> ReviewAssignmentResponse:
    assignment, created = service.transfer(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        review_id=review_id,
        assignment_id=assignment_id,
        request=request,
        kind="delegate",
    )
    if not created:
        response.status_code = 200
    return assignment


@router.post("/{review_id}/comments", response_model=ReviewCommentResponse, status_code=201)
def add_review_comment(
    review_id: UUID,
    request: CreateReviewCommentRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    response: Response,
) -> ReviewCommentResponse:
    comment, created = service.comment(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        review_id=review_id,
        request=request,
    )
    if not created:
        response.status_code = 200
    return comment


def review_conflict_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "review_revision_conflict"})
