from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.schemas import ErrorResponse
from agreement_intelligence_api.comparisons.repository import SQLAlchemyVersionComparisonRepository
from agreement_intelligence_api.comparisons.schemas import (
    CreateVersionComparisonRequest,
    VersionComparisonResultResponse,
    VersionComparisonRunResponse,
)
from agreement_intelligence_api.comparisons.service import (
    VersionComparisonService,
)
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.queue import (
    ProcessingQueuePublisher,
    queue_publisher_from_environment,
)
from agreement_intelligence_api.processing.repository import SQLAlchemyProcessingJobRepository

router = APIRouter(prefix="/agreements", tags=["version-comparisons"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=255)]


def _queue() -> ProcessingQueuePublisher:
    return queue_publisher_from_environment()


QueueDependency = Annotated[ProcessingQueuePublisher, Depends(_queue)]


def _service(session: SessionDependency, queue: QueueDependency) -> VersionComparisonService:
    return VersionComparisonService(
        SQLAlchemyVersionComparisonRepository(session),
        SQLAlchemyAgreementRepository(session),
        SQLAlchemyProcessingJobRepository(session),
        IdentityService(session),
        queue,
    )


ServiceDependency = Annotated[VersionComparisonService, Depends(_service)]


async def comparison_conflict_handler(request: Request, _: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=ErrorResponse(
            code="version_comparison_conflict",
            message="The requested version comparison cannot be created",
            correlation_id=request.state.correlation_id,
        ).model_dump(),
    )


@router.post(
    "/{agreement_id}/version-comparisons",
    response_model=VersionComparisonRunResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_comparison(
    agreement_id: UUID,
    request: CreateVersionComparisonRequest,
    response: Response,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
    idempotency_key: IdempotencyKey,
) -> VersionComparisonRunResponse:
    comparison, created = service.create(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        idempotency_key=idempotency_key,
        request=request,
    )
    if not created:
        response.status_code = 200
    return comparison


@router.get(
    "/{agreement_id}/version-comparisons/{comparison_id}",
    response_model=VersionComparisonResultResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_comparison(
    agreement_id: UUID,
    comparison_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
) -> VersionComparisonResultResponse:
    return service.get(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        comparison_id=comparison_id,
    )
