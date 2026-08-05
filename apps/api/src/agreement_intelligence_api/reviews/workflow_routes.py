from hashlib import sha256
from json import dumps, loads
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.audit.models import AuditEventRecord
from agreement_intelligence_api.audit.service import AuditEventWriter
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.storage import storage_from_environment
from agreement_intelligence_api.identity.authz import Principal, current_principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.export import _render_pdf
from agreement_intelligence_api.reviews.models import (
    ReviewCaseRecord,
    ReviewCommentRecord,
    ReviewFinalPackageRecord,
    ReviewWorkflowDecisionRecord,
    ReviewWorkflowRecord,
)
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


@router.get("/{review_id}/timeline")
def review_timeline(
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> list[dict[str, object]]:
    """Return one authorized, chronological view of comments, decisions, and audit events."""
    review = _review_for_permission(session, review_id, principal, PermissionKey.AGREEMENTS_READ)
    comments = session.scalars(
        select(ReviewCommentRecord)
        .where(ReviewCommentRecord.review_id == review.id)
        .where(ReviewCommentRecord.organization_id == review.organization_id)
        .where(ReviewCommentRecord.workspace_id == review.workspace_id)
    ).all()
    decisions = session.scalars(
        select(ReviewWorkflowDecisionRecord)
        .join(
            ReviewWorkflowRecord,
            ReviewWorkflowRecord.id == ReviewWorkflowDecisionRecord.workflow_id,
        )
        .where(ReviewWorkflowRecord.review_id == review.id)
    ).all()
    audits = session.scalars(
        select(AuditEventRecord)
        .where(AuditEventRecord.organization_id == review.organization_id)
        .where(AuditEventRecord.workspace_id == review.workspace_id)
        .where(AuditEventRecord.resource_id.in_([review.id]))
    ).all()
    events: list[dict[str, object]] = [
        {
            "kind": "comment",
            "id": str(item.id),
            "actor_id": str(item.author_id),
            "occurred_at": item.created_at.isoformat(),
            "body": item.body,
            "finding_id": str(item.finding_id) if item.finding_id else None,
        }
        for item in comments
    ]
    events.extend(
        {
            "kind": "decision",
            "id": str(item.id),
            "actor_id": str(item.actor_id),
            "occurred_at": item.occurred_at.isoformat(),
            "action": item.action,
            "stage_id": str(item.workflow_stage_id),
        }
        for item in decisions
    )
    events.extend(
        {
            "kind": "audit",
            "id": str(item.id),
            "actor_id": str(item.actor_id),
            "occurred_at": item.occurred_at.isoformat(),
            "action": item.action,
            "outcome": item.outcome,
        }
        for item in audits
    )
    return sorted(events, key=lambda event: (str(event["occurred_at"]), str(event["id"])))


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
    package = session.scalar(
        select(ReviewFinalPackageRecord).where(ReviewFinalPackageRecord.review_id == review.id)
    )
    if package is None:
        package = _create_final_package(session, review, workflow)
    base = f"/reviews/{review.id}/final-package"
    return FinalReviewPackageResponse(
        pdf_url=f"{base}/pdf",
        manifest_url=f"{base}/manifest",
        checksum=f"sha256:{package.manifest_checksum}",
        created_at=package.created_at.isoformat(),
        manifest_checksum=f"sha256:{package.manifest_checksum}",
        pdf_checksum=f"sha256:{package.pdf_checksum}",
    )


@router.get("/{review_id}/final-package/manifest")
def download_final_package_manifest(
    review_id: UUID, principal: PrincipalDependency, session: SessionDependency
) -> dict[str, object]:
    review = _review_for_permission(session, review_id, principal, PermissionKey.AGREEMENTS_READ)
    record = _stored_package(session, review)
    document = storage_from_environment().read(record.manifest_key)
    if document is None:
        raise HTTPException(status_code=404, detail="final_package_unavailable")
    return cast(dict[str, object], loads(document.content))


@router.get("/{review_id}/final-package/pdf")
def download_final_package_pdf(
    review_id: UUID, principal: PrincipalDependency, session: SessionDependency
) -> Response:
    review = _review_for_permission(session, review_id, principal, PermissionKey.AGREEMENTS_READ)
    record = _stored_package(session, review)
    document = storage_from_environment().read(record.pdf_key)
    if document is None:
        raise HTTPException(status_code=404, detail="final_package_unavailable")
    return Response(content=document.content, media_type="application/pdf")


def _stored_package(session: Session, review: ReviewCaseRecord) -> ReviewFinalPackageRecord:
    package = session.scalar(
        select(ReviewFinalPackageRecord).where(
            ReviewFinalPackageRecord.review_id == review.id,
            ReviewFinalPackageRecord.organization_id == review.organization_id,
            ReviewFinalPackageRecord.workspace_id == review.workspace_id,
        )
    )
    if package is None:
        workflow = session.scalar(
            select(ReviewWorkflowRecord).where(ReviewWorkflowRecord.review_id == review.id)
        )
        if workflow is None or workflow.state not in {"approved", "rejected", "revision_requested"}:
            raise HTTPException(status_code=409, detail="final_package_not_ready")
        package = _create_final_package(session, review, workflow)
    return package


def _create_final_package(
    session: Session, review: ReviewCaseRecord, workflow: ReviewWorkflowRecord
) -> ReviewFinalPackageRecord:
    if workflow.state not in {"approved", "rejected", "revision_requested"}:
        raise HTTPException(status_code=409, detail="final_package_not_ready")
    decisions = session.scalars(
        select(ReviewWorkflowDecisionRecord)
        .where(ReviewWorkflowDecisionRecord.workflow_id == workflow.id)
        .order_by(ReviewWorkflowDecisionRecord.occurred_at)
    ).all()
    manifest = {
        "review_id": str(review.id),
        "agreement_id": str(review.agreement_id),
        "agreement_version_id": (
            str(review.agreement_version_id) if review.agreement_version_id else None
        ),
        "workflow_id": str(workflow.id),
        "policy_version_id": str(workflow.policy_version_id),
        "state": workflow.state,
        "revision": workflow.revision,
        "decisions": [
            {
                "actor_id": str(item.actor_id),
                "action": item.action,
                "stage_id": str(item.workflow_stage_id),
                "occurred_at": item.occurred_at.isoformat(),
            }
            for item in decisions
        ],
        "provenance": {"source": "postgresql", "workflow_revision": workflow.revision},
    }
    manifest_content = dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_checksum = sha256(manifest_content).hexdigest()
    pdf_content = _render_pdf(
        [
            "Agreement Intelligence - Final Review Package",
            f"Agreement ID: {review.agreement_id}",
            f"Review ID: {review.id}",
            f"Outcome: {workflow.state}",
            f"Manifest checksum: sha256:{manifest_checksum}",
        ]
    )
    pdf_checksum = sha256(pdf_content).hexdigest()
    base = f"reviews/{review.organization_id}/{review.workspace_id}/{review.id}/final-package"
    manifest_key = f"{base}/manifest.json"
    pdf_key = f"{base}/report.pdf"
    storage = storage_from_environment()
    storage.put_immutable(
        manifest_key, manifest_content, content_type="application/json", sha256=manifest_checksum
    )
    storage.put_immutable(pdf_key, pdf_content, content_type="application/pdf", sha256=pdf_checksum)
    package = ReviewFinalPackageRecord(
        organization_id=review.organization_id,
        workspace_id=review.workspace_id,
        review_id=review.id,
        workflow_id=workflow.id,
        state=workflow.state,
        manifest_key=manifest_key,
        pdf_key=pdf_key,
        manifest_checksum=manifest_checksum,
        pdf_checksum=pdf_checksum,
    )
    session.add(package)
    AuditEventWriter(session).record(
        organization_id=review.organization_id,
        workspace_id=review.workspace_id,
        actor_id=review.created_by,
        action="review_final_package_generated",
        resource_type="review_final_package",
        resource_id=package.id,
        outcome="accepted",
        correlation_id=f"review-package-{review.id}",
        before_ref={"state": "not_generated"},
        after_ref={
            "state": workflow.state,
            "manifest_checksum": manifest_checksum,
            "pdf_checksum": pdf_checksum,
        },
        metadata={"review_id": str(review.id), "workflow_id": str(workflow.id)},
    )
    session.commit()
    session.refresh(package)
    return package


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
