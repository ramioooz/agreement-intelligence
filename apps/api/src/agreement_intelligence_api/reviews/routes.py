from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.routes import get_document_service
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.decisions import ReviewDecisionService
from agreement_intelligence_api.reviews.export import ReviewReportService
from agreement_intelligence_api.reviews.schemas import (
    PlaybookEvaluationResponse,
    ReviewDecisionHistoryResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    SubmitPlaybookEvaluationRequest,
)
from agreement_intelligence_api.reviews.service import PlaybookEvaluationService

router = APIRouter(prefix="/agreements", tags=["reviews"])
decision_router = APIRouter(prefix="/review-findings", tags=["reviews"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


def get_service(request: Request, session: SessionDependency) -> PlaybookEvaluationService:
    return PlaybookEvaluationService(
        session,
        IdentityService(session),
        get_document_service(request)._storage,
    )


ServiceDependency = Annotated[PlaybookEvaluationService, Depends(get_service)]


def get_decision_service(session: SessionDependency) -> ReviewDecisionService:
    return ReviewDecisionService(session, IdentityService(session))


def get_report_service(session: SessionDependency) -> ReviewReportService:
    return ReviewReportService(session, IdentityService(session))


DecisionServiceDependency = Annotated[ReviewDecisionService, Depends(get_decision_service)]
ReportServiceDependency = Annotated[ReviewReportService, Depends(get_report_service)]


@router.post(
    "/{agreement_id}/playbook-evaluations",
    response_model=PlaybookEvaluationResponse,
    status_code=201,
)
def submit_playbook_evaluation(
    agreement_id: UUID,
    request: SubmitPlaybookEvaluationRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> PlaybookEvaluationResponse:
    return service.submit(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        request=request,
    )


@router.get("/{agreement_id}/playbook-evaluations", response_model=list[PlaybookEvaluationResponse])
def list_playbook_evaluations(
    agreement_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> list[PlaybookEvaluationResponse]:
    return service.list(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )


@decision_router.post(
    "/{finding_id}/decisions",
    response_model=ReviewDecisionResponse,
    status_code=201,
)
def record_review_decision(
    finding_id: UUID,
    request: ReviewDecisionRequest,
    principal: PrincipalDependency,
    service: DecisionServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewDecisionResponse:
    return service.record(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        finding_id=finding_id,
        request=request,
    )


@decision_router.get(
    "/{finding_id}/decisions",
    response_model=ReviewDecisionHistoryResponse,
)
def get_review_decisions(
    finding_id: UUID,
    principal: PrincipalDependency,
    service: DecisionServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ReviewDecisionHistoryResponse:
    return service.history(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        finding_id=finding_id,
    )


@router.get("/{agreement_id}/review-report", response_class=Response)
def export_review_report(
    agreement_id: UUID,
    principal: PrincipalDependency,
    service: ReportServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> Response:
    report = service.export(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )
    return Response(
        content=report.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.filename}"'},
    )
