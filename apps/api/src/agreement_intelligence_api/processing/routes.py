from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.repository import SQLAlchemyAgreementRepository
from agreement_intelligence_api.agreements.schemas import ErrorResponse
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.limits import LimitScope, RateLimitPolicy, enforce_rate_limit
from agreement_intelligence_api.processing.queue import (
    ProcessingQueuePublisher,
    queue_publisher_from_environment,
)
from agreement_intelligence_api.processing.repository import SQLAlchemyProcessingJobRepository
from agreement_intelligence_api.processing.schemas import (
    ProcessingJobResponse,
    SubmitProcessingJobRequest,
)
from agreement_intelligence_api.processing.service import ProcessingJobService
from agreement_intelligence_api.usage import UsageAmount, UsageLedgerService

router = APIRouter(prefix="/agreements", tags=["processing"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=255)]


def get_queue_publisher() -> ProcessingQueuePublisher:
    return queue_publisher_from_environment()


QueuePublisherDependency = Annotated[ProcessingQueuePublisher, Depends(get_queue_publisher)]


def get_service(
    session: SessionDependency, queue: QueuePublisherDependency
) -> ProcessingJobService:
    return ProcessingJobService(
        SQLAlchemyProcessingJobRepository(session),
        SQLAlchemyAgreementRepository(session),
        IdentityService(session),
        queue,
    )


ServiceDependency = Annotated[ProcessingJobService, Depends(get_service)]


async def idempotency_conflict_handler(request: Request, _: Exception) -> JSONResponse:
    return _error_response(
        request,
        409,
        "idempotency_key_conflict",
        "Idempotency key was already used with a different processing request",
    )


async def retry_not_permitted_handler(request: Request, _: Exception) -> JSONResponse:
    return _error_response(
        request,
        409,
        "retry_not_permitted",
        "This processing job is not eligible for retry",
    )


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        correlation_id=request.state.correlation_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@router.post(
    "/{agreement_id}/processing-jobs",
    response_model=ProcessingJobResponse,
    status_code=202,
    responses={409: {"model": ErrorResponse}},
)
def submit_processing_job(
    agreement_id: UUID,
    request: SubmitProcessingJobRequest,
    response: Response,
    principal: PrincipalDependency,
    session: SessionDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
    idempotency_key: IdempotencyKey,
) -> ProcessingJobResponse:
    return _submit_with_usage_control(
        service=service,
        session=session,
        principal=principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        version_id=None,
        idempotency_key=idempotency_key,
        request=request,
        response=response,
    )


@router.post(
    "/{agreement_id}/versions/{version_id}/processing-jobs",
    response_model=ProcessingJobResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def submit_version_processing_job(
    agreement_id: UUID,
    version_id: UUID,
    request: SubmitProcessingJobRequest,
    response: Response,
    principal: PrincipalDependency,
    session: SessionDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
    idempotency_key: IdempotencyKey,
) -> ProcessingJobResponse:
    return _submit_with_usage_control(
        service=service,
        session=session,
        principal=principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        version_id=version_id,
        idempotency_key=idempotency_key,
        request=request,
        response=response,
    )


def _submit_with_usage_control(
    *,
    service: ProcessingJobService,
    session: Session,
    principal: Principal,
    organization_id: UUID,
    workspace_id: UUID,
    agreement_id: UUID,
    version_id: UUID | None,
    idempotency_key: str,
    request: SubmitProcessingJobRequest,
    response: Response,
) -> ProcessingJobResponse:
    if not IdentityService(session).can_access_workspace(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=PermissionKey.AGREEMENTS_UPDATE,
    ):
        from agreement_intelligence_api.agreements.service import AgreementNotFoundError

        raise AgreementNotFoundError
    existing = service.existing_submission(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        version_id=version_id,
        idempotency_key=idempotency_key,
        request=request,
    )
    if existing is not None:
        response.status_code = 200
        return existing
    scope = LimitScope(organization_id, workspace_id, principal.user_id)
    enforce_rate_limit(
        scope=scope,
        operation=f"processing.submit.{request.profile}",
        policy=RateLimitPolicy(limit=30, window_seconds=300, expensive=True),
    )
    usage = UsageLedgerService(session)
    reservation_id = uuid5(
        NAMESPACE_URL,
        f"{organization_id}:{workspace_id}:{agreement_id}:{idempotency_key}",
    )
    reservation = usage.reserve_usage(
        scope=scope,
        operation=f"processing.{request.profile}",
        provider="openai",
        configuration_version="model-gateway.v1",
        estimated=UsageAmount(tokens=12_000, cost_usd=0.10),
        reservation_id=reservation_id,
    )
    if not reservation.allowed:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": reservation.reason},
        )
    try:
        job, created = service.submit(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            version_id=version_id,
            idempotency_key=idempotency_key,
            request=request,
        )
    except Exception:
        usage.cancel_usage(reservation_id)
        raise
    if not created:
        response.status_code = 200
    return job


@router.get(
    "/{agreement_id}/processing-jobs/{job_id}",
    response_model=ProcessingJobResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_processing_job(
    agreement_id: UUID,
    job_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
) -> ProcessingJobResponse:
    return service.get(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        job_id=job_id,
    )


@router.post(
    "/{agreement_id}/processing-jobs/{job_id}/retry",
    response_model=ProcessingJobResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def retry_processing_job(
    agreement_id: UUID,
    job_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
) -> ProcessingJobResponse:
    return service.retry(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        job_id=job_id,
    )


@router.post(
    "/{agreement_id}/processing-jobs/{job_id}/requeue",
    response_model=ProcessingJobResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def requeue_processing_job(
    agreement_id: UUID,
    job_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
) -> ProcessingJobResponse:
    return service.requeue(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_id=agreement_id,
        job_id=job_id,
    )
