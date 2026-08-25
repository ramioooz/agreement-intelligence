from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from agreement_intelligence_worker.evidence_validation import (
    AnswerCandidate,
    Answerer,
    Citation,
    GroundedClaim,
    extract_supporting_quote,
)
from agreement_intelligence_worker.model_gateway import (
    GatewayProvenance,
    GroundedAnswerRequest,
    ModelGateway,
    embedding_configuration_from_environment,
    embedding_gateway_from_environment,
    model_gateway_from_environment,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agreement_intelligence_api.db import get_session
from agreement_intelligence_api.identity.authz import Principal, current_principal
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.limits import LimitScope, RateLimitPolicy, enforce_rate_limit
from agreement_intelligence_api.qa.repository import SQLAlchemyQuestionRepository
from agreement_intelligence_api.qa.schemas import (
    AnswerResponse,
    CitationResponse,
    ClaimResponse,
    CreateQuestionThreadRequest,
    QuestionRequest,
    QuestionThreadResponse,
    QuestionTurnResponse,
)
from agreement_intelligence_api.qa.service import (
    GroundedQuestionService,
    QuestionThread,
    QuestionThreadView,
    QuestionTurn,
)
from agreement_intelligence_api.search.repository import SQLAlchemySearchRepository
from agreement_intelligence_api.search.service import (
    HybridSearchService,
    SQLAlchemySemanticCandidateProvider,
)
from agreement_intelligence_api.usage import UsageAmount, UsageLedgerService

router = APIRouter(prefix="/questions", tags=["questions"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def _service(
    session: Session,
    *,
    usage_recorder: Callable[[GatewayProvenance], None] | None = None,
) -> GroundedQuestionService:
    search_repository = SQLAlchemySearchRepository(session)
    search = HybridSearchService(
        search_repository,
        IdentityService(session),
        SQLAlchemySemanticCandidateProvider(
            search_repository,
            gateway=embedding_gateway_from_environment(),
            configuration=embedding_configuration_from_environment(),
        ),
    )
    return GroundedQuestionService(
        search=search,
        identity=IdentityService(session),
        answerer=_gateway_answerer(model_gateway_from_environment(), usage_recorder=usage_recorder),
        repository=SQLAlchemyQuestionRepository(session),
    )


def get_service(session: SessionDependency) -> GroundedQuestionService:
    return _service(session)


QuestionServiceDependency = Annotated[GroundedQuestionService, Depends(get_service)]


@router.post("/threads", response_model=QuestionThreadResponse, status_code=201)
def create_thread(
    payload: CreateQuestionThreadRequest,
    principal: PrincipalDependency,
    service: QuestionServiceDependency,
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
) -> QuestionThreadResponse:
    thread = service.create_thread(
        principal,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agreement_ids=tuple(payload.agreement_ids) if payload.agreement_ids else None,
    )
    return _thread_response(QuestionThreadView(thread=thread, turns=()))


@router.get("/threads/{thread_id}", response_model=QuestionThreadResponse)
def get_thread(
    thread_id: UUID,
    principal: PrincipalDependency,
    service: QuestionServiceDependency,
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
) -> QuestionThreadResponse:
    view = service.read_thread(
        principal,
        thread=QuestionThread(
            id=thread_id, organization_id=organization_id, workspace_id=workspace_id
        ),
    )
    if view is None:
        from agreement_intelligence_api.identity.authz import hide_resource

        hide_resource()
    return _thread_response(view)


@router.post("/threads/{thread_id}/turns", response_model=QuestionTurnResponse, status_code=201)
def create_turn(
    thread_id: UUID,
    payload: QuestionRequest,
    principal: PrincipalDependency,
    session: SessionDependency,
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
) -> QuestionTurnResponse:
    thread = QuestionThread(
        id=thread_id, organization_id=organization_id, workspace_id=workspace_id
    )
    if _service(session).read_thread(principal, thread=thread) is None:
        from agreement_intelligence_api.identity.authz import hide_resource

        hide_resource()
    scope = LimitScope(organization_id, workspace_id, principal.user_id)
    enforce_rate_limit(
        scope=scope,
        operation="qa.turn",
        policy=RateLimitPolicy(limit=10, window_seconds=60, expensive=True),
    )
    estimated = UsageAmount(tokens=6_000, cost_usd=0.05)
    usage = UsageLedgerService(session)
    reservation = usage.reserve_usage(
        scope=scope,
        operation="model.generate.answer",
        provider="openai",
        configuration_version="model-gateway.v1",
        estimated=estimated,
    )
    if not reservation.allowed:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": reservation.reason},
        )

    usage_settled = False

    def settle(provenance: GatewayProvenance) -> None:
        nonlocal usage_settled
        if reservation.reservation_id is None:
            return
        usage.settle_usage(
            reservation.reservation_id,
            actual=UsageAmount(
                tokens=provenance.total_tokens or estimated.tokens,
                cost_usd=provenance.cost_usd
                if provenance.cost_usd is not None
                else estimated.cost_usd,
            ),
            settlement_key=f"qa:{reservation.reservation_id}",
        )
        usage_settled = True

    service = _service(session, usage_recorder=settle)
    turn = service.ask(
        principal,
        thread=thread,
        question=payload.question,
    )
    if reservation.reservation_id is not None and not usage_settled:
        usage.cancel_usage(reservation.reservation_id)
        session.commit()
    return _turn_response(turn)


def _gateway_answerer(
    gateway: ModelGateway | None,
    *,
    usage_recorder: Callable[[GatewayProvenance], None] | None = None,
) -> Answerer:
    def answer(request: object) -> AnswerCandidate:
        from agreement_intelligence_worker.evidence_validation import GroundedQuestionRequest

        if gateway is None or not isinstance(request, GroundedQuestionRequest):
            raise RuntimeError("model gateway unavailable")
        requested_evidence = {item.anchor.anchor_id: item.text for item in request.evidence}
        result = gateway.answer(
            GroundedAnswerRequest(
                question=request.question,
                evidence=tuple(requested_evidence.items()),
                conversation_context=request.conversation_context,
                organization_id=request.organization_id,
                workspace_id=request.workspace_id,
            )
        )
        if usage_recorder is not None:
            usage_recorder(result.provenance)
        citations = tuple(
            Citation(
                anchor_id=anchor_id,
                supporting_quote=extract_supporting_quote(
                    result.answer, requested_evidence[anchor_id]
                )
                or "",
            )
            for anchor_id in result.citation_ids
        )
        return AnswerCandidate(
            claims=(
                GroundedClaim(
                    text=result.answer,
                    citations=citations,
                ),
            )
        )

    return answer


def _thread_response(view: QuestionThreadView) -> QuestionThreadResponse:
    return QuestionThreadResponse(
        id=view.thread.id,
        organization_id=view.thread.organization_id,
        workspace_id=view.thread.workspace_id,
        agreement_ids=list(view.thread.agreement_ids) if view.thread.agreement_ids else None,
        turns=[_turn_response(turn) for turn in view.turns],
    )


def _turn_response(turn: QuestionTurn) -> QuestionTurnResponse:
    return QuestionTurnResponse(
        id=turn.id,
        question=turn.question,
        created_at=turn.created_at,
        answer=AnswerResponse(
            status=turn.answer.status,
            message=turn.answer.message,
            claims=[
                ClaimResponse(
                    text=claim.text,
                    citations=[
                        CitationResponse(
                            anchor_id=citation.anchor_id,
                            supporting_quote=citation.supporting_quote,
                            agreement_id=source.agreement_id,
                            source_checksum=source.source_checksum,
                            source_version=source.source_version,
                        )
                        for citation in claim.citations
                        if (source := turn.citation_sources.get(citation.anchor_id)) is not None
                    ],
                )
                for claim in turn.answer.claims
            ],
        ),
    )
