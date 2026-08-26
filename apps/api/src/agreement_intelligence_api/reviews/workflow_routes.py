from hashlib import sha256
from json import loads
from typing import Annotated, NoReturn, cast
from uuid import UUID

from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.audit.models import AuditEventRecord
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.storage import (
    DocumentStorage,
    StoredDocument,
    storage_from_environment,
)
from agreement_intelligence_api.identity.authz import Principal, current_principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
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
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


@router.get("/{review_id}/timeline")
def review_timeline(
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> list[dict[str, object]]:
    """Return one authorized, chronological view of comments, decisions, and audit events."""
    review = _review_for_permission(
        session,
        review_id,
        principal,
        PermissionKey.AGREEMENTS_READ,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
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
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewWorkflowResponse:
    review = _review_for_permission(
        session,
        review_id,
        principal,
        PermissionKey.REVIEWS_ASSIGN,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    snapshot = ReviewWorkflowCoordinator(session).start(
        review_id=review.id,
        policy_version_id=body.policy_version_id,
        correlation_id=request.state.correlation_id,
    )
    ReviewWorkflowQueueDispatcher(
        session, workflow_queue_publisher_from_environment()
    ).dispatch_pending(organization_id=organization_id, workspace_id=workspace_id)
    return _response(snapshot)


@router.get("/{review_id}/workflow", response_model=ReviewWorkflowResponse)
def get_workflow(
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewWorkflowResponse:
    review = _review_for_permission(
        session,
        review_id,
        principal,
        PermissionKey.AGREEMENTS_READ,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
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
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> FinalReviewPackageResponse:
    review = _review_for_permission(
        session,
        review_id,
        principal,
        PermissionKey.AGREEMENTS_READ,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    workflow = session.scalar(
        select(ReviewWorkflowRecord).where(ReviewWorkflowRecord.review_id == review.id)
    )
    if workflow is None or workflow.state not in {"approved", "rejected", "revision_requested"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="final_package_not_ready")
    package = session.scalar(
        select(ReviewFinalPackageRecord).where(
            ReviewFinalPackageRecord.review_id == review.id,
            ReviewFinalPackageRecord.organization_id == review.organization_id,
            ReviewFinalPackageRecord.workspace_id == review.workspace_id,
        )
    )
    if package is None:
        _package_retryable("final_package_pending")
    storage = storage_from_environment()
    _verified_package_document(
        storage,
        key=package.manifest_key,
        checksum=package.manifest_checksum,
        content_type="application/json",
    )
    _verified_package_document(
        storage,
        key=package.pdf_key,
        checksum=package.pdf_checksum,
        content_type="application/pdf",
    )
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
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> dict[str, object]:
    review = _review_for_permission(
        session,
        review_id,
        principal,
        PermissionKey.AGREEMENTS_READ,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    record = _stored_package(session, review)
    document = _verified_package_document(
        storage_from_environment(),
        key=record.manifest_key,
        checksum=record.manifest_checksum,
        content_type="application/json",
    )
    return cast(dict[str, object], loads(document.content))


@router.get("/{review_id}/final-package/pdf")
def download_final_package_pdf(
    review_id: UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> Response:
    review = _review_for_permission(
        session,
        review_id,
        principal,
        PermissionKey.AGREEMENTS_READ,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    record = _stored_package(session, review)
    document = _verified_package_document(
        storage_from_environment(),
        key=record.pdf_key,
        checksum=record.pdf_checksum,
        content_type="application/pdf",
    )
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
        _package_retryable("final_package_pending")
    return package


def _verified_package_document(
    storage: DocumentStorage,
    *,
    key: str,
    checksum: str,
    content_type: str,
) -> StoredDocument:
    try:
        document = storage.read(key)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {
            "SlowDown",
            "RequestTimeout",
            "InternalError",
            "ServiceUnavailable",
            "Throttling",
            "ThrottlingException",
        } or (isinstance(status_code, int) and status_code >= 500):
            _package_retryable("final_package_unavailable")
        raise
    except (
        EndpointConnectionError,
        ConnectTimeoutError,
        ConnectionClosedError,
        ReadTimeoutError,
    ):
        _package_retryable("final_package_unavailable")
    if (
        document is None
        or document.content_type != content_type
        or sha256(document.content).hexdigest() != checksum
    ):
        _package_retryable("final_package_unavailable")
    return document


def _package_retryable(code: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "retryable": True},
        headers={"Retry-After": "3"},
    )


@router.post("/{review_id}/workflow/decisions", response_model=ReviewWorkflowResponse)
def decide_workflow(
    review_id: UUID,
    body: ReviewWorkflowDecisionRequest,
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewWorkflowResponse:
    review = _review_for_any_permission(
        session,
        review_id,
        principal,
        (PermissionKey.REVIEWS_DECIDE, PermissionKey.REVIEWS_APPROVE),
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
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
    ).dispatch_pending(organization_id=organization_id, workspace_id=workspace_id)
    return _response(snapshot)


def _review_for_permission(
    session: Session,
    review_id: UUID,
    principal: Principal,
    permission: PermissionKey,
    *,
    organization_id: UUID,
    workspace_id: UUID,
) -> ReviewCaseRecord:
    identity = IdentityService(session)
    if not identity.can_access_workspace(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=permission,
    ):
        hide_resource()
    review = session.scalar(
        select(ReviewCaseRecord)
        .join(AgreementRecord, ReviewCaseRecord.agreement_id == AgreementRecord.id)
        .where(
            ReviewCaseRecord.id == review_id,
            ReviewCaseRecord.organization_id == organization_id,
            ReviewCaseRecord.workspace_id == workspace_id,
            AgreementRecord.deletion_requested_at.is_(None),
        )
    )
    if review is None:
        hide_resource()
    return review


def _review_for_any_permission(
    session: Session,
    review_id: UUID,
    principal: Principal,
    permissions: tuple[PermissionKey, ...],
    *,
    organization_id: UUID,
    workspace_id: UUID,
) -> ReviewCaseRecord:
    identity = IdentityService(session)
    if not any(
        identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=permission,
        )
        for permission in permissions
    ):
        hide_resource()
    review = session.scalar(
        select(ReviewCaseRecord)
        .join(AgreementRecord, ReviewCaseRecord.agreement_id == AgreementRecord.id)
        .where(
            ReviewCaseRecord.id == review_id,
            ReviewCaseRecord.organization_id == organization_id,
            ReviewCaseRecord.workspace_id == workspace_id,
            AgreementRecord.deletion_requested_at.is_(None),
        )
    )
    if review is None:
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
