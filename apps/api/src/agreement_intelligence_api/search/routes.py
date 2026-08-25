from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from agreement_intelligence_worker.model_gateway import (
    GatewayProvenance,
    embedding_configuration_from_environment,
    embedding_gateway_from_environment,
)
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from agreement_intelligence_api.agreements.service import AgreementNotFoundError
from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.limits import LimitScope, RateLimitPolicy, enforce_rate_limit
from agreement_intelligence_api.search.repository import SQLAlchemySearchRepository
from agreement_intelligence_api.search.schemas import SearchFilters, SearchResponse
from agreement_intelligence_api.search.service import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    HybridSearchService,
    SearchNotAuthorizedError,
    SQLAlchemySemanticCandidateProvider,
)
from agreement_intelligence_api.usage import UsageAmount, UsageLedgerService

router = APIRouter(prefix="/search", tags=["search"])

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def _service(
    session: Session,
    *,
    usage_recorder: Callable[[GatewayProvenance], None] | None = None,
    semantic_enabled: bool = True,
) -> HybridSearchService:
    repository = SQLAlchemySearchRepository(session)
    return HybridSearchService(
        repository,
        IdentityService(session),
        SQLAlchemySemanticCandidateProvider(
            repository,
            gateway=embedding_gateway_from_environment() if semantic_enabled else None,
            configuration=embedding_configuration_from_environment(),
            usage_recorder=usage_recorder,
        ),
    )


def get_service(session: SessionDependency) -> HybridSearchService:
    return _service(session)


@router.get("", response_model=SearchResponse)
def search_agreements(
    principal: PrincipalDependency,
    session: SessionDependency,
    response: Response,
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
    identity = IdentityService(session)
    if not identity.can_access_workspace(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        permission=PermissionKey.SEARCH_QUERY,
    ):
        raise AgreementNotFoundError
    scope = LimitScope(organization_id, workspace_id, principal.user_id)
    enforce_rate_limit(
        scope=scope,
        operation="search.query",
        policy=RateLimitPolicy(limit=60, window_seconds=60, expensive=False),
    )
    usage = UsageLedgerService(session)
    configuration = embedding_configuration_from_environment()
    estimated = UsageAmount(
        tokens=512,
        cost_usd=512 * configuration.input_cost_per_million_tokens / 1_000_000,
    )
    reservation = usage.reserve_usage(
        scope=scope,
        operation="model.embed.query",
        provider="openai",
        configuration_version=configuration.configuration_version,
        estimated=estimated,
    )
    semantic_enabled = reservation.allowed
    if not semantic_enabled:
        response.headers["X-Semantic-Search"] = "degraded"

    usage_settled = False

    def settle(provenance: GatewayProvenance) -> None:
        nonlocal usage_settled
        if reservation.reservation_id is None:
            return
        usage.settle_usage(
            reservation.reservation_id,
            actual=UsageAmount(
                tokens=provenance.total_tokens or provenance.input_tokens or estimated.tokens,
                cost_usd=provenance.cost_usd
                if provenance.cost_usd is not None
                else estimated.cost_usd,
            ),
            settlement_key=f"search:{reservation.reservation_id}",
        )
        usage_settled = True

    service = _service(
        session,
        usage_recorder=settle if semantic_enabled else None,
        semantic_enabled=semantic_enabled,
    )
    try:
        result = service.search(
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
        if reservation.reservation_id is not None and not usage_settled:
            usage.cancel_usage(reservation.reservation_id)
        session.commit()
        return result
    except SearchNotAuthorizedError as error:
        # Do not expose whether the requested workspace contains documents.
        raise AgreementNotFoundError from error
