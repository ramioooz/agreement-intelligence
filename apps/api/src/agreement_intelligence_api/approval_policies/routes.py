from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agreement_intelligence_api.approval_policies.schemas import (
    ApprovalPolicyRouteRequest,
    ApprovalPolicyVersionResponse,
    CreateApprovalPolicyRequest,
    CreateApprovalPolicyVersionRequest,
    DocumentDirection,
    Materiality,
    SupportedAgreementFamily,
)
from agreement_intelligence_api.approval_policies.service import ApprovalPolicyService
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService

router = APIRouter(prefix="/approval-policies", tags=["approval-policies"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
OrganizationScope = Annotated[UUID, Query()]
WorkspaceScope = Annotated[UUID, Query()]


def get_service(session: SessionDependency) -> ApprovalPolicyService:
    return ApprovalPolicyService(session, IdentityService(session))


ServiceDependency = Annotated[ApprovalPolicyService, Depends(get_service)]


@router.post("", response_model=ApprovalPolicyVersionResponse, status_code=201)
def create_approval_policy(
    request: CreateApprovalPolicyRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ApprovalPolicyVersionResponse:
    return service.create(
        principal, organization_id=organization_id, workspace_id=workspace_id, request=request
    )


@router.get("", response_model=list[ApprovalPolicyVersionResponse])
def list_approval_policies(
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    agreement_family: str | None = Query(default=None, min_length=1, max_length=100),
) -> list[ApprovalPolicyVersionResponse]:
    return service.list(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_family=agreement_family,
    )


@router.get("/route", response_model=ApprovalPolicyVersionResponse | None)
def route_approval_policy(
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
    agreement_family: SupportedAgreementFamily,
    document_direction: DocumentDirection = "any",
    jurisdiction: str = "any",
    materiality: Materiality = "any",
) -> ApprovalPolicyVersionResponse | None:
    return service.route(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        request=ApprovalPolicyRouteRequest(
            agreement_family=agreement_family,
            document_direction=document_direction,
            jurisdiction=jurisdiction,
            materiality=materiality,
        ),
    )


@router.post("/{policy_id}/versions", response_model=ApprovalPolicyVersionResponse, status_code=201)
def create_approval_policy_version(
    policy_id: UUID,
    request: CreateApprovalPolicyVersionRequest,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ApprovalPolicyVersionResponse:
    return service.create_version(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        policy_id=policy_id,
        request=request,
    )


@router.post(
    "/{policy_id}/versions/{version_number}/publish", response_model=ApprovalPolicyVersionResponse
)
def publish_approval_policy_version(
    policy_id: UUID,
    version_number: int,
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: OrganizationScope,
    workspace_id: WorkspaceScope,
) -> ApprovalPolicyVersionResponse:
    return service.publish(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        policy_id=policy_id,
        version_number=version_number,
    )
