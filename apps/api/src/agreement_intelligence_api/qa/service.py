"""Service boundary for fresh, authorization-scoped grounded Q&A."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from agreement_intelligence_worker.evidence_validation import (
    Answerer,
    EvidenceAnchor,
    EvidenceSnippet,
    GroundedAnswer,
    answer_question,
)

from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.qa.models import QuestionThreadRecord, QuestionTurnRecord
from agreement_intelligence_api.qa.repository import SQLAlchemyQuestionRepository
from agreement_intelligence_api.search.schemas import SearchFilters, SearchResponse


@dataclass(frozen=True)
class QuestionThread:
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    agreement_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True)
class QuestionTurn:
    id: UUID
    question: str
    answer: GroundedAnswer
    created_at: datetime


@dataclass
class QuestionThreadView:
    thread: QuestionThread
    turns: tuple[QuestionTurn, ...]


class SearchService(Protocol):
    def search(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int = 20,
    ) -> SearchResponse: ...


class Identity(Protocol):
    def can_access_workspace(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        permission: PermissionKey,
    ) -> bool: ...


class GroundedQuestionService:
    """Question execution always retrieves and authorizes evidence anew."""

    def __init__(
        self,
        *,
        search: SearchService,
        identity: Identity,
        answerer: Answerer,
        repository: SQLAlchemyQuestionRepository | None = None,
    ) -> None:
        self._search = search
        self._identity = identity
        self._answerer = answerer
        self._repository = repository
        self._turns: dict[UUID, list[QuestionTurn]] = {}

    def create_thread(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_ids: tuple[UUID, ...] | None = None,
    ) -> QuestionThread:
        self._require_access(principal, organization_id=organization_id, workspace_id=workspace_id)
        thread = QuestionThread(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_ids=agreement_ids,
        )
        self._turns[thread.id] = []
        if self._repository is not None:
            self._repository.add_thread(
                QuestionThreadRecord(
                    id=thread.id,
                    organization_id=thread.organization_id,
                    workspace_id=thread.workspace_id,
                    agreement_ids=(
                        [str(value) for value in agreement_ids] if agreement_ids else None
                    ),
                    created_by=principal.user_id,
                )
            )
        return thread

    def read_thread(
        self, principal: Principal, *, thread: QuestionThread
    ) -> QuestionThreadView | None:
        persisted = self._load_thread(thread)
        if persisted is None or not self._can_access(principal, persisted):
            return None
        return QuestionThreadView(
            thread=persisted,
            turns=tuple(self._load_turns(persisted)),
        )

    def ask(self, principal: Principal, *, thread: QuestionThread, question: str) -> QuestionTurn:
        persisted = self._load_thread(thread)
        if persisted is None:
            raise PermissionError("question thread is not available")
        self._require_access(
            principal,
            organization_id=persisted.organization_id,
            workspace_id=persisted.workspace_id,
        )
        # Search is deliberately performed for every turn. History does not grant evidence access.
        results = self._search.search(
            principal,
            organization_id=persisted.organization_id,
            workspace_id=persisted.workspace_id,
            filters=SearchFilters(query=question, agreement_ids=persisted.agreement_ids),
        )
        answer = answer_question(
            question=question,
            authorized_evidence=_evidence_from_search(results),
            answerer=lambda request: self._answerer(
                replace(
                    request,
                    conversation_context=_validated_context(self._load_turns(persisted)[-10:]),
                )
            ),
        )
        turn = QuestionTurn(
            id=uuid4(), question=question, answer=answer, created_at=datetime.now(UTC)
        )
        self._turns.setdefault(persisted.id, []).append(turn)
        if self._repository is not None:
            self._repository.add_turn(
                QuestionTurnRecord(
                    id=turn.id,
                    organization_id=persisted.organization_id,
                    workspace_id=persisted.workspace_id,
                    thread_id=persisted.id,
                    question=turn.question,
                    answer_status=turn.answer.status,
                    answer_message=turn.answer.message,
                    claims=_claims_payload(turn.answer),
                    retrieval_provenance={"result_count": len(results.items)},
                )
            )
        return turn

    def _load_thread(self, thread: QuestionThread) -> QuestionThread | None:
        if self._repository is None:
            return thread if thread.id in self._turns else None
        record = self._repository.get_thread(
            organization_id=thread.organization_id,
            workspace_id=thread.workspace_id,
            thread_id=thread.id,
        )
        if record is None:
            return None
        return QuestionThread(
            id=record.id,
            organization_id=record.organization_id,
            workspace_id=record.workspace_id,
            agreement_ids=tuple(UUID(value) for value in record.agreement_ids or ()) or None,
        )

    def _load_turns(self, thread: QuestionThread) -> list[QuestionTurn]:
        if self._repository is None:
            return self._turns.get(thread.id, [])
        return [
            _turn_from_record(record)
            for record in self._repository.list_turns(
                organization_id=thread.organization_id,
                workspace_id=thread.workspace_id,
                thread_id=thread.id,
            )
        ]

    def _can_access(self, principal: Principal, thread: QuestionThread) -> bool:
        return self._identity.can_access_workspace(
            principal,
            organization_id=thread.organization_id,
            workspace_id=thread.workspace_id,
            permission=PermissionKey.SEARCH_QUERY,
        )

    def _require_access(
        self, principal: Principal, *, organization_id: UUID, workspace_id: UUID
    ) -> None:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.SEARCH_QUERY,
        ):
            raise PermissionError("question thread is not available")


def _evidence_from_search(results: SearchResponse) -> tuple[EvidenceSnippet, ...]:
    evidence: list[EvidenceSnippet] = []
    for result in results.items:
        for anchor_id in result.citation.anchor_ids:
            evidence.append(
                EvidenceSnippet(
                    anchor=EvidenceAnchor(
                        anchor_id=anchor_id,
                        source_checksum=result.citation.source_checksum,
                        page_number=1,
                        start_offset=0,
                        end_offset=len(result.content_preview),
                    ),
                    text=result.content_preview,
                )
            )
    return tuple(evidence)


def _claims_payload(answer: GroundedAnswer) -> list[dict[str, object]]:
    return [
        {
            "text": claim.text,
            "citations": [
                {"anchor_id": citation.anchor_id, "supporting_quote": citation.supporting_quote}
                for citation in claim.citations
            ],
        }
        for claim in answer.claims
    ]


def _turn_from_record(record: QuestionTurnRecord) -> QuestionTurn:
    from agreement_intelligence_worker.evidence_validation import Citation, GroundedClaim

    claims = tuple(
        GroundedClaim(
            text=str(payload["text"]),
            citations=tuple(
                Citation(
                    anchor_id=str(citation["anchor_id"]),
                    supporting_quote=str(citation["supporting_quote"]),
                )
                for citation in cast(list[object], payload.get("citations", []))
                if isinstance(citation, dict)
            ),
        )
        for payload in record.claims
        if isinstance(payload, dict) and isinstance(payload.get("text"), str)
    )
    return QuestionTurn(
        id=record.id,
        question=record.question,
        answer=GroundedAnswer(
            status=record.answer_status,  # type: ignore[arg-type]
            claims=claims,
            message=record.answer_message,
        ),
        created_at=record.created_at,
    )


def _validated_context(turns: list[QuestionTurn]) -> tuple[str, ...]:
    """Only accepted claims—not historical evidence—can provide context."""
    return tuple(
        claim.text
        for turn in turns
        if turn.answer.status in {"answered", "partial"}
        for claim in turn.answer.claims
    )
