from __future__ import annotations

from typing import Annotated
from uuid import UUID

from agreement_intelligence_worker.evidence_validation import (
    AnswerCandidate,
    Answerer,
    Citation,
    GroundedClaim,
)
from agreement_intelligence_worker.model_gateway import (
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

router = APIRouter(prefix="/questions", tags=["questions"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def get_service(session: SessionDependency) -> GroundedQuestionService:
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
        answerer=_gateway_answerer(model_gateway_from_environment()),
        repository=SQLAlchemyQuestionRepository(session),
    )


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
    service: QuestionServiceDependency,
    organization_id: Annotated[UUID, Query()],
    workspace_id: Annotated[UUID, Query()],
) -> QuestionTurnResponse:
    turn = service.ask(
        principal,
        thread=QuestionThread(
            id=thread_id, organization_id=organization_id, workspace_id=workspace_id
        ),
        question=payload.question,
    )
    return _turn_response(turn)


def _gateway_answerer(gateway: ModelGateway | None) -> Answerer:
    def answer(request: object) -> AnswerCandidate:
        from agreement_intelligence_worker.evidence_validation import GroundedQuestionRequest

        if gateway is None or not isinstance(request, GroundedQuestionRequest):
            raise RuntimeError("model gateway unavailable")
        result = gateway.generate_json(
            instruction=request.instructions,
            payload={
                "question": request.question,
                "conversation_context": list(request.conversation_context),
                "evidence": [
                    {"anchor_id": item.anchor.anchor_id, "text": item.text}
                    for item in request.evidence
                ],
                "response_contract": {
                    "claims": [
                        {
                            "text": "string",
                            "citations": [{"anchor_id": "string", "supporting_quote": "string"}],
                        }
                    ]
                },
            },
        )
        raw_claims = result.payload.get("claims")
        if not isinstance(raw_claims, list):
            return AnswerCandidate(claims=())
        claims: list[GroundedClaim] = []
        for raw_claim in raw_claims:
            if not isinstance(raw_claim, dict) or not isinstance(raw_claim.get("text"), str):
                continue
            raw_citations = raw_claim.get("citations")
            if not isinstance(raw_citations, list):
                continue
            citations = tuple(
                Citation(
                    anchor_id=item["anchor_id"],
                    supporting_quote=item["supporting_quote"],
                )
                for item in raw_citations
                if isinstance(item, dict)
                and isinstance(item.get("anchor_id"), str)
                and isinstance(item.get("supporting_quote"), str)
            )
            claims.append(GroundedClaim(text=raw_claim["text"], citations=citations))
        return AnswerCandidate(claims=tuple(claims))

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
                        )
                        for citation in claim.citations
                    ],
                )
                for claim in turn.answer.claims
            ],
        ),
    )
