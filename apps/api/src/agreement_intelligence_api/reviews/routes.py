from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.routes import get_document_service
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.schemas import (
    PlaybookEvaluationResponse,
    SubmitPlaybookEvaluationRequest,
)
from agreement_intelligence_api.reviews.service import PlaybookEvaluationService

router = APIRouter(prefix="/agreements", tags=["reviews"])

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
