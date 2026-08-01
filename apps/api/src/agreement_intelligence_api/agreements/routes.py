from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.schemas import (
    AgreementListResponse,
    AgreementResponse,
    CreateAgreementRequest,
    ErrorResponse,
)
from agreement_intelligence_api.agreements.service import AgreementNotFoundError, AgreementService
from agreement_intelligence_api.analysis.service import load_analysis
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.documents.routes import get_document_service
from agreement_intelligence_api.documents.service import UploadScope
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)

router = APIRouter(prefix="/agreements", tags=["agreements"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


def get_service(session: SessionDependency) -> AgreementService:
    return AgreementService(
        SQLAlchemyAgreementRepository(session),
        IdentityService(session),
    )


AgreementServiceDependency = Annotated[AgreementService, Depends(get_service)]


async def agreement_not_found_handler(
    request: Request,
    _: Exception,
) -> JSONResponse:
    payload = ErrorResponse(
        code="agreement_not_found",
        message="Agreement not found",
        correlation_id=request.state.correlation_id,
    )
    return JSONResponse(status_code=404, content=payload.model_dump())


@router.post("", response_model=AgreementResponse, status_code=201)
def create_agreement(
    request: CreateAgreementRequest,
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AgreementResponse:
    return service.create(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        request=request,
    )


@router.get("", response_model=AgreementListResponse)
def list_agreements(
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[int, Query(ge=0)] = 0,
    query: str | None = Query(default=None, min_length=1, max_length=500),
    agreement_type: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
) -> AgreementListResponse:
    return service.list(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
        cursor=cursor,
        query=query,
        agreement_type=agreement_type,
        status=status,
        include_archived=include_archived,
    )


@router.get(
    "/{agreement_id}", response_model=AgreementResponse, responses={404: {"model": ErrorResponse}}
)
def get_agreement(
    agreement_id: UUID,
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AgreementResponse:
    return service.get(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )


@router.get(
    "/{agreement_id}/analysis",
    responses={404: {"model": ErrorResponse}},
)
def get_document_analysis(
    agreement_id: UUID,
    request: Request,
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    session: SessionDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    processing_job_id: UUID | None = None,
) -> dict[str, object]:
    service.get(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )
    artifact_query = (
        select(ProcessingArtifactRecord.artifact_key)
        .join(ProcessingJobRecord, ProcessingArtifactRecord.job_id == ProcessingJobRecord.id)
        .where(ProcessingArtifactRecord.agreement_id == agreement_id)
        .where(ProcessingJobRecord.organization_id == organization_id)
        .where(ProcessingJobRecord.workspace_id == workspace_id)
        .where(ProcessingJobRecord.state == "completed")
        .order_by(desc(ProcessingArtifactRecord.created_at))
        .limit(1)
    )
    if processing_job_id is not None:
        artifact_query = artifact_query.where(ProcessingJobRecord.id == processing_job_id)
    artifact_key = session.scalar(artifact_query)
    storage = get_document_service(request)._storage
    analysis = load_analysis(storage, artifact_key)
    if analysis is None:
        raise AgreementNotFoundError
    return analysis


@router.delete("/{agreement_id}", status_code=204, responses={404: {"model": ErrorResponse}})
def delete_agreement(
    agreement_id: UUID,
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    request: Request,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> Response:
    agreement, object_keys = service.deletion_object_keys(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )
    get_document_service(request).delete(
        UploadScope(tenant_id=agreement.organization_id, workspace_id=agreement.workspace_id),
        object_keys=object_keys,
    )
    service.permanently_delete(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )
    return Response(status_code=204)


@router.post(
    "/{agreement_id}/archive",
    response_model=AgreementResponse,
    responses={404: {"model": ErrorResponse}},
)
def archive_agreement(
    agreement_id: UUID,
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AgreementResponse:
    return service.archive(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )


@router.post(
    "/{agreement_id}/restore",
    response_model=AgreementResponse,
    responses={404: {"model": ErrorResponse}},
)
def restore_agreement(
    agreement_id: UUID,
    principal: PrincipalDependency,
    service: AgreementServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AgreementResponse:
    return service.restore(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
    )
