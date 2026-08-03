from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.service import AgreementNotFoundError
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.search.repository import SQLAlchemySearchRepository
from agreement_intelligence_api.search.schemas import SearchFilters, SearchResponse
from agreement_intelligence_api.search.service import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    HybridSearchService,
    SearchNotAuthorizedError,
)

router = APIRouter(prefix="/search", tags=["search"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def get_service(session: SessionDependency) -> HybridSearchService:
    return HybridSearchService(SQLAlchemySearchRepository(session), IdentityService(session))


SearchServiceDependency = Annotated[HybridSearchService, Depends(get_service)]


@router.get("", response_model=SearchResponse)
def search_agreements(
    principal: PrincipalDependency,
    service: SearchServiceDependency,
    organization_id: UUID,
    workspace_id: UUID,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    agreement_type: str | None = None,
    party: str | None = None,
    status: str | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    source_version: str | None = None,
    agreement_id: Annotated[list[UUID] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_RESULT_LIMIT)] = DEFAULT_RESULT_LIMIT,
) -> SearchResponse:
    try:
        return service.search(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            filters=SearchFilters(
                query=query,
                agreement_type=agreement_type,
                party=party,
                status=status,
                updated_after=updated_after,
                updated_before=updated_before,
                source_version=source_version,
                agreement_ids=tuple(agreement_id) if agreement_id else None,
            ),
            limit=limit,
        )
    except SearchNotAuthorizedError as error:
        # Do not expose whether the requested workspace contains documents.
        raise AgreementNotFoundError from error
