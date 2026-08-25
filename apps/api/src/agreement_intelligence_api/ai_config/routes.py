from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agreement_intelligence_api.ai_config.schemas import (
    AIConfigurationPromotionResponse,
    AIConfigurationResponse,
    CreateAIConfigurationRequest,
    PromoteAIConfigurationRequest,
)
from agreement_intelligence_api.ai_config.service import AIConfigurationService
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.queue import (
    ProcessingQueuePublisher,
    queue_publisher_from_environment,
)

router = APIRouter(prefix="/ai-configurations", tags=["ai-configurations"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


def get_queue_publisher() -> ProcessingQueuePublisher:
    return queue_publisher_from_environment()


QueuePublisherDependency = Annotated[ProcessingQueuePublisher, Depends(get_queue_publisher)]


def get_service(
    session: SessionDependency,
    queue: QueuePublisherDependency,
) -> AIConfigurationService:
    return AIConfigurationService(session, IdentityService(session), queue=queue)


ServiceDependency = Annotated[AIConfigurationService, Depends(get_service)]


@router.post("", response_model=AIConfigurationResponse, status_code=201)
def create_configuration(
    request: CreateAIConfigurationRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AIConfigurationResponse:
    return service.create(
        principal, organization_id=organization_id, workspace_id=workspace_id, request=request
    )


@router.get("", response_model=list[AIConfigurationResponse])
def list_configurations(
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> list[AIConfigurationResponse]:
    return service.list(principal, organization_id=organization_id, workspace_id=workspace_id)


@router.get("/resolve", response_model=AIConfigurationResponse | None)
def resolve_configuration(
    operation: str,
    environment: str,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    configuration_id: UUID | None = None,
) -> AIConfigurationResponse | None:
    service._authorize(principal, organization_id=organization_id, workspace_id=workspace_id)
    return service.resolve(
        organization_id=organization_id,
        workspace_id=workspace_id,
        operation=operation,
        environment=environment,
        configuration_id=configuration_id,
    )


@router.get("/{configuration_id}", response_model=AIConfigurationResponse)
def get_configuration(
    configuration_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AIConfigurationResponse:
    return service.get(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        configuration_id=configuration_id,
    )


@router.post("/{configuration_id}/validate", response_model=AIConfigurationResponse)
def validate_configuration(
    configuration_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AIConfigurationResponse:
    return service.validate(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        configuration_id=configuration_id,
    )


@router.post("/{configuration_id}/publish", response_model=AIConfigurationResponse)
def publish_configuration(
    configuration_id: UUID,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AIConfigurationResponse:
    return service.publish(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        configuration_id=configuration_id,
    )


@router.post(
    "/{configuration_id}/promotions",
    response_model=AIConfigurationPromotionResponse,
    status_code=201,
)
def promote_configuration(
    configuration_id: UUID,
    request: PromoteAIConfigurationRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> AIConfigurationPromotionResponse:
    return service.promote(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        configuration_id=configuration_id,
        environment=request.environment,
    )
