from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService

router = APIRouter(prefix="/identity", tags=["identity"])

SessionDependency = Annotated[Session, Depends(get_session)]


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str


class WorkspaceCapabilitiesResponse(BaseModel):
    agreements_delete: bool


def get_identity_service(session: SessionDependency) -> IdentityService:
    return IdentityService(session)


PrincipalDependency = Annotated[Principal, Depends(current_principal)]
IdentityServiceDependency = Annotated[IdentityService, Depends(get_identity_service)]


@router.get(
    "/organizations/{organization_id}/workspaces",
    response_model=list[WorkspaceResponse],
)
def list_workspaces(
    organization_id: UUID,
    principal: PrincipalDependency,
    identity: IdentityServiceDependency,
) -> list[WorkspaceResponse]:
    workspaces = identity.list_workspaces_for_organization(
        principal, organization_id=organization_id
    )
    if workspaces is None:
        hide_resource()
    return [
        WorkspaceResponse(id=workspace.id, name=workspace.name, slug=workspace.slug)
        for workspace in workspaces
    ]


@router.get(
    "/organizations/{organization_id}/workspaces/{workspace_id}/capabilities",
    response_model=WorkspaceCapabilitiesResponse,
)
def get_workspace_capabilities(
    organization_id: UUID,
    workspace_id: UUID,
    principal: PrincipalDependency,
    identity: IdentityServiceDependency,
) -> WorkspaceCapabilitiesResponse:
    if not identity.can_access_workspace(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=PermissionKey.AGREEMENTS_READ,
    ):
        hide_resource()
    return WorkspaceCapabilitiesResponse(
        agreements_delete=identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AGREEMENTS_DELETE,
        )
    )
