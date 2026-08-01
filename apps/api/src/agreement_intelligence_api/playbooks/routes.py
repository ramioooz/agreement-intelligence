from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.playbooks.schemas import (
    CreatePlaybookRequest,
    CreatePlaybookVersionRequest,
    PlaybookRuleWrite,
    PlaybookVersionResponse,
    UpdatePlaybookRuleRequest,
)
from agreement_intelligence_api.playbooks.service import PlaybookService

router = APIRouter(prefix="/playbooks", tags=["playbooks"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


def get_service(session: SessionDependency) -> PlaybookService:
    return PlaybookService(session, IdentityService(session))


PlaybookServiceDependency = Annotated[PlaybookService, Depends(get_service)]


@router.post("", response_model=PlaybookVersionResponse, status_code=201)
def create_playbook(
    request: CreatePlaybookRequest,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> PlaybookVersionResponse:
    return service.create(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        request=request,
    )


@router.post("/{playbook_id}/versions", response_model=PlaybookVersionResponse, status_code=201)
def create_playbook_version(
    playbook_id: UUID,
    request: CreatePlaybookVersionRequest,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> PlaybookVersionResponse:
    return service.create_version(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        playbook_id=playbook_id,
        request=request,
    )


@router.get("", response_model=list[PlaybookVersionResponse])
def list_playbooks(
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    agreement_family: str | None = Query(default=None, min_length=1, max_length=100),
) -> list[PlaybookVersionResponse]:
    return service.list(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_family=agreement_family,
    )


@router.post(
    "/{playbook_id}/versions/{version_number}/rules",
    response_model=PlaybookVersionResponse,
    status_code=201,
)
def add_playbook_rule(
    playbook_id: UUID,
    version_number: int,
    request: PlaybookRuleWrite,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> PlaybookVersionResponse:
    return service.add_rule(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        playbook_id=playbook_id,
        version_number=version_number,
        request=request,
    )


@router.put(
    "/{playbook_id}/versions/{version_number}/rules/{rule_id}",
    response_model=PlaybookVersionResponse,
)
def update_playbook_rule(
    playbook_id: UUID,
    version_number: int,
    rule_id: UUID,
    request: UpdatePlaybookRuleRequest,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> PlaybookVersionResponse:
    return service.update_rule(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        playbook_id=playbook_id,
        version_number=version_number,
        rule_id=rule_id,
        request=request,
    )


@router.delete("/{playbook_id}/versions/{version_number}/rules/{rule_id}", status_code=204)
def delete_playbook_rule(
    playbook_id: UUID,
    version_number: int,
    rule_id: UUID,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    confirm: bool = False,
) -> Response:
    service.delete_rule(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        playbook_id=playbook_id,
        version_number=version_number,
        rule_id=rule_id,
        confirmed=confirm,
    )
    return Response(status_code=204)


@router.post(
    "/{playbook_id}/versions/{version_number}/publish",
    response_model=PlaybookVersionResponse,
)
def publish_playbook_version(
    playbook_id: UUID,
    version_number: int,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> PlaybookVersionResponse:
    return service.publish(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        playbook_id=playbook_id,
        version_number=version_number,
    )


@router.delete("/{playbook_id}/versions/{version_number}", status_code=204)
def delete_playbook_version(
    playbook_id: UUID,
    version_number: int,
    principal: PrincipalDependency,
    service: PlaybookServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    confirm: bool = False,
) -> Response:
    service.delete_version(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        playbook_id=playbook_id,
        version_number=version_number,
        confirmed=confirm,
    )
    return Response(status_code=204)
