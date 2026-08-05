from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agreement_intelligence_api.audit.schemas import AuditEventResponse
from agreement_intelligence_api.audit.service import AuditLedgerService
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService

router = APIRouter(prefix="/audit-events", tags=["audit"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def get_service(session: SessionDependency) -> AuditLedgerService:
    return AuditLedgerService(session, IdentityService(session))


ServiceDependency = Annotated[AuditLedgerService, Depends(get_service)]


@router.get("", response_model=list[AuditEventResponse])
def list_audit_events(
    principal: PrincipalDependency,
    service: ServiceDependency,
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[AuditEventResponse]:
    return service.list_events(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
    )
