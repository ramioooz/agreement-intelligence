from hashlib import sha256
from json import dumps
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.export import _render_pdf
from agreement_intelligence_api.reviews.models import ReviewCaseRecord, ReviewWorkflowRecord
from agreement_intelligence_api.reviews.workflow import (
    ReviewWorkflowCoordinator,
    ReviewWorkflowQueueDispatcher,
    WorkflowSnapshot,
    workflow_queue_publisher_from_environment,
)
from agreement_intelligence_api.reviews.workflow_schemas import (
    FinalReviewPackageResponse,
    ReviewWorkflowDecisionRequest,
    ReviewWorkflowResponse,
    ReviewWorkflowStageResponse,
    StartReviewWorkflowRequest,
)

router = APIRouter(prefix="/reviews", tags=["review-workflows"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


@router.post("/{review_id}/workflow", response_model=ReviewWorkflowResponse, status_code=201)
def start_workflow(
    review_id: UUID,
    body: StartReviewWorkflowRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> ReviewWorkflowResponse:
    review = _review_for_permission(session, review_id, principal, PermissionKey.REVIEWS_ASSIGN)
    snapshot = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=body.policy_version_id,
        correlation_id=request.state.correlation_id,
    )
    ReviewWorkflowQueueDispatcher(
        session, workflow_queue_publisher_from_environment()
    ).dispatch_pending()
    return _response(snapshot)


@router.get("/{review_id}/workflow", response_model=ReviewWorkflowResponse)
def get_workflow(
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> ReviewWorkflowResponse:
    review = _review_for_permission(session, review_id, principal, PermissionKey.AGREEMENTS_READ)
    workflow = session.scalar(
        select(ReviewWorkflowRecord).where(ReviewWorkflowRecord.review_id == review.id)
    )
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workflow_not_started")
    return ReviewWorkflowResponse(
        id=workflow.id,
        state=workflow.state,
        active_stage_ordinal=workflow.active_stage_ordinal,
        checkpoint_id=workflow.checkpoint_id,
        revision=workflow.revision,
        stages=[
            ReviewWorkflowStageResponse(ordinal=item.ordinal, state=item.state)
            for item in workflow.stages
        ],
    )


@router.get("/{review_id}/final-package", response_model=FinalReviewPackageResponse)
def get_final_package(
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> FinalReviewPackageResponse:
    review = _review_for_permission(session, review_id, principal, PermissionKey.AGREEMENTS_READ)
    workflow = session.scalar(
        select(ReviewWorkflowRecord).where(ReviewWorkflowRecord.review_id == review.id)
    )
    if workflow is None or workflow.state not in {"approved", "rejected", "revision_requested"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="final_package_not_ready")
    checksum = sha256(
        dumps(
            {
                "review_id": str(review.id),
                "workflow_id": str(workflow.id),
                "state": workflow.state,
                "revision": workflow.revision,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    base = f"/reviews/{review.id}/final-package"
    return FinalReviewPackageResponse(
        pdf_url=f"{base}/pdf",
        manifest_url=f"{base}/manifest",
        checksum=f"sha256:{checksum}",
        created_at=workflow.updated_at.isoformat(),
    )


@router.get("/{review_id}/final-package/manifest")
def download_final_package_manifest(
    review_id: UUID, principal: PrincipalDependency, session: SessionDependency
) -> dict[str, object]:
    package = get_final_package(review_id, principal, session)
    return {"review_id": str(review_id), "package": package.model_dump()}


@router.get("/{review_id}/final-package/pdf")
def download_final_package_pdf(
    review_id: UUID, principal: PrincipalDependency, session: SessionDependency
) -> Response:
    package = get_final_package(review_id, principal, session)
    content = _render_pdf(
        [
            "Agreement Intelligence - Final Review Package",
            f"Review ID: {review_id}",
            f"Checksum: {package.checksum}",
            f"Generated at: {package.created_at}",
        ]
    )
    return Response(content=content, media_type="application/pdf")


@router.post("/{review_id}/workflow/decisions", response_model=ReviewWorkflowResponse)
def decide_workflow(
    review_id: UUID,
    body: ReviewWorkflowDecisionRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> ReviewWorkflowResponse:
    review = _review_for_permission(session, review_id, principal, PermissionKey.REVIEWS_APPROVE)
    workflow = session.scalar(
        select(ReviewWorkflowRecord).where(ReviewWorkflowRecord.review_id == review.id)
    )
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workflow_not_started")
    snapshot = ReviewWorkflowCoordinator(session).decide(
        workflow_id=workflow.id,
        actor_id=principal.user_id,
        action=body.action,  # type: ignore[arg-type]
        idempotency_key=body.idempotency_key,
        expected_revision=body.expected_revision,
        correlation_id=request.state.correlation_id,
    )
    ReviewWorkflowQueueDispatcher(
        session, workflow_queue_publisher_from_environment()
    ).dispatch_pending()
    return _response(snapshot)


def _review_for_permission(
    session: Session, review_id: UUID, principal: Principal, permission: PermissionKey
) -> ReviewCaseRecord:
    review = session.get(ReviewCaseRecord, review_id)
    if review is None:
        hide_resource()
    if not IdentityService(session).can_access_workspace(
        principal,
        organization_id=review.organization_id,
        workspace_id=review.workspace_id,
        permission=permission,
    ):
        hide_resource()
    return review


def _response(snapshot: WorkflowSnapshot) -> ReviewWorkflowResponse:
    return ReviewWorkflowResponse(
        id=snapshot.id,
        state=snapshot.state,
        active_stage_ordinal=snapshot.active_stage_ordinal,
        checkpoint_id=snapshot.checkpoint_id,
        revision=snapshot.revision,
        stages=[
            ReviewWorkflowStageResponse(ordinal=item.ordinal, state=item.state)
            for item in snapshot.stages
        ],
    )


def workflow_conflict_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": "review_workflow_conflict"}
    )
