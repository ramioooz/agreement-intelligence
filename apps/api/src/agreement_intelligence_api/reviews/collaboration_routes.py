from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

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
    response: Response,
) -> ReviewCaseResponse:
    review, created = service.start(
        principal, organization_id=organization_id, workspace_id=workspace_id, request=request
    )
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
