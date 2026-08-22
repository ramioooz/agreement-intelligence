"""Service boundary for fresh, authorization-scoped grounded Q&A."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from agreement_intelligence_worker.evidence_validation import (
    Answerer,
    AnswerStatus,
    EvidenceAnchor,
    EvidenceSnippet,
    GroundedAnswer,
    answer_question,
)
from agreement_intelligence_worker.guardrails import GuardrailDecision

from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.qa.models import (
    QuestionAuditEventRecord,
    QuestionThreadRecord,
    QuestionTurnRecord,
)
from agreement_intelligence_api.qa.repository import SQLAlchemyQuestionRepository
from agreement_intelligence_api.search.schemas import SearchFilters, SearchResponse


@dataclass(frozen=True)
class QuestionThread:
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    agreement_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True)
class CitationSource:
    agreement_id: UUID
    source_checksum: str
    source_version: str


@dataclass(frozen=True)
class QuestionTurn:
    id: UUID
    question: str
    answer: GroundedAnswer
    created_at: datetime
    citation_sources: dict[str, CitationSource] = field(default_factory=dict)


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
            try:
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
                self._repository.add_audit_event(
                    QuestionAuditEventRecord(
                        organization_id=thread.organization_id,
                        workspace_id=thread.workspace_id,
                        thread_id=thread.id,
                        turn_id=None,
                        actor_id=principal.user_id,
                        action="thread_created",
                        outcome="created",
                        metadata_json={},
                    )
                )
                self._repository.commit()
            except Exception:
                self._repository.rollback()
                self._turns.pop(thread.id, None)
                raise
        return thread

    def read_thread(
        self, principal: Principal, *, thread: QuestionThread
    ) -> QuestionThreadView | None:
        persisted = self._load_thread(thread)
        if persisted is None or not self._can_access(principal, persisted):
            return None
        return QuestionThreadView(
            thread=persisted,
            turns=tuple(self._redact_inaccessible_turns(persisted)),
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
        citation_sources = _citation_sources_from_search(results)
        answer = answer_question(
            question=question,
            authorized_evidence=_evidence_from_search(results, citation_sources),
            answerer=lambda request: self._answerer(
                replace(
                    request,
                    conversation_context=_validated_context(
                        self._redact_inaccessible_turns(persisted)[-10:]
                    ),
                )
            ),
        )
        turn = QuestionTurn(
            id=uuid4(),
            question=question,
            answer=answer,
            created_at=datetime.now(UTC),
            citation_sources=citation_sources,
        )
        self._turns.setdefault(persisted.id, []).append(turn)
        if self._repository is not None:
            try:
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
                        retrieval_provenance={
                            "result_count": len(results.items),
                            "citation_sources": _citation_sources_payload(citation_sources),
                            "guardrail": turn.answer.guardrail_decision.provenance(),
                        },
                    )
                )
                self._repository.add_audit_event(
                    QuestionAuditEventRecord(
                        organization_id=persisted.organization_id,
                        workspace_id=persisted.workspace_id,
                        thread_id=persisted.id,
                        turn_id=turn.id,
                        actor_id=principal.user_id,
                        action="question_answered",
                        outcome=turn.answer.status,
                        metadata_json={},
                    )
                )
                self._repository.commit()
            except Exception:
                self._repository.rollback()
                self._turns.get(persisted.id, []).remove(turn)
                raise
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

    def _redact_inaccessible_turns(self, thread: QuestionThread) -> list[QuestionTurn]:
        turns = self._load_turns(thread)
        if self._repository is None:
            return turns
        agreement_ids = {
            source.agreement_id for turn in turns for source in turn.citation_sources.values()
        }
        visible_agreement_ids = self._repository.visible_agreement_ids(
            organization_id=thread.organization_id,
            workspace_id=thread.workspace_id,
            agreement_ids=agreement_ids,
        )
        return [_redact_turn(turn, visible_agreement_ids) for turn in turns]

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


def _citation_sources_from_search(results: SearchResponse) -> dict[str, CitationSource]:
    sources: dict[str, CitationSource] = {}
    ambiguous_anchor_ids: set[str] = set()
    for result in results.items:
        source = CitationSource(
            agreement_id=result.agreement_id,
            source_checksum=result.citation.source_checksum,
            source_version=result.citation.source_version,
        )
        for anchor_id in result.citation.anchor_ids:
            existing = sources.get(anchor_id)
            if existing is None:
                sources[anchor_id] = source
            elif existing != source:
                ambiguous_anchor_ids.add(anchor_id)
    for anchor_id in ambiguous_anchor_ids:
        sources.pop(anchor_id, None)
    return sources


def _evidence_from_search(
    results: SearchResponse, citation_sources: dict[str, CitationSource]
) -> tuple[EvidenceSnippet, ...]:
    evidence: list[EvidenceSnippet] = []
    for result in results.items:
        for anchor_id in result.citation.anchor_ids:
            if anchor_id not in citation_sources:
                continue
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


def _citation_sources_payload(
    citation_sources: dict[str, CitationSource],
) -> dict[str, dict[str, str]]:
    return {
        anchor_id: {
            "agreement_id": str(source.agreement_id),
            "source_checksum": source.source_checksum,
            "source_version": source.source_version,
        }
        for anchor_id, source in citation_sources.items()
    }


def _citation_sources_from_payload(payload: dict[str, object]) -> dict[str, CitationSource]:
    raw_sources = payload.get("citation_sources")
    if not isinstance(raw_sources, dict):
        return {}
    sources: dict[str, CitationSource] = {}
    for anchor_id, raw_source in raw_sources.items():
        if not isinstance(anchor_id, str) or not isinstance(raw_source, dict):
            continue
        agreement_id = raw_source.get("agreement_id")
        source_checksum = raw_source.get("source_checksum")
        source_version = raw_source.get("source_version")
        if not (
            isinstance(agreement_id, str)
            and isinstance(source_checksum, str)
            and isinstance(source_version, str)
        ):
            continue
        try:
            sources[anchor_id] = CitationSource(
                agreement_id=UUID(agreement_id),
                source_checksum=source_checksum,
                source_version=source_version,
            )
        except ValueError:
            continue
    return sources


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
    guardrail_decision = _guardrail_decision_from_payload(record.retrieval_provenance)
    if guardrail_decision is None:
        return QuestionTurn(
            id=record.id,
            question=record.question,
            answer=GroundedAnswer(
                status="insufficient_evidence",
                claims=(),
                message="Prior evidence provenance is unavailable.",
                guardrail_decision=GuardrailDecision(
                    "review", ("invalid_persisted_guardrail_provenance",)
                ),
            ),
            created_at=record.created_at,
            citation_sources={},
        )
    return QuestionTurn(
        id=record.id,
        question=record.question,
        answer=GroundedAnswer(
            status=(
                _answer_status(record.answer_status)
                if guardrail_decision.status == "allow"
                else "insufficient_evidence"
            ),
            claims=claims if guardrail_decision.status == "allow" else (),
            message=(
                record.answer_message
                if guardrail_decision.status == "allow"
                else "Prior evidence requires review."
            ),
            guardrail_decision=guardrail_decision,
        ),
        created_at=record.created_at,
        citation_sources=_citation_sources_from_payload(record.retrieval_provenance),
    )


def _guardrail_decision_from_payload(payload: dict[str, object]) -> GuardrailDecision | None:
    value = payload.get("guardrail")
    if not isinstance(value, dict) or set(value) != {"policy_version", "status", "reason_codes"}:
        return None
    version = value.get("policy_version")
    status = value.get("status")
    reasons = value.get("reason_codes")
    if (
        version != "untrusted-evidence.v1"
        or status not in {"allow", "review", "block"}
        or not isinstance(reasons, list)
        or not all(isinstance(reason, str) for reason in reasons)
    ):
        return None
    blocking_reasons = {
        "unknown_anchor_id",
        "prompt_exfiltration_request",
        "encoded_exfiltration_request",
        "tool_or_write_action_request",
    }
    review_reasons = {"instruction_override_marker"}
    known_reasons = blocking_reasons | review_reasons
    if len(reasons) != len(set(reasons)) or any(reason not in known_reasons for reason in reasons):
        return None
    if (
        (status == "allow" and reasons)
        or (
            status == "review"
            and (not reasons or any(reason not in review_reasons for reason in reasons))
        )
        or (status == "block" and not any(reason in blocking_reasons for reason in reasons))
    ):
        return None
    return GuardrailDecision(
        cast(Literal["allow", "review", "block"], status), tuple(reasons), version
    )


def _validated_context(turns: list[QuestionTurn]) -> tuple[str, ...]:
    """Only accepted claims—not historical evidence—can provide context."""
    return tuple(
        claim.text
        for turn in turns
        if turn.answer.status in {"answered", "partial"}
        and turn.answer.guardrail_decision.status == "allow"
        for claim in turn.answer.claims
    )


def _answer_status(value: str) -> AnswerStatus:
    if value in {
        "answered",
        "insufficient_evidence",
        "conflicting_evidence",
        "partial",
        "model_unavailable",
    }:
        return cast(AnswerStatus, value)
    return "insufficient_evidence"


def _redact_turn(turn: QuestionTurn, visible_agreement_ids: set[UUID]) -> QuestionTurn:
    """Return a display-safe historical turn without mutating its audit record.

    Persisted answers are historical output, not an authorization grant. A
    claim survives only when every citation can still be navigated to an
    agreement that remains visible in the current workspace scope.
    """

    valid_anchor_ids = {
        anchor_id
        for anchor_id, source in turn.citation_sources.items()
        if source.agreement_id in visible_agreement_ids
    }
    claims = tuple(
        claim
        for claim in turn.answer.claims
        if claim.citations
        and all(citation.anchor_id in valid_anchor_ids for citation in claim.citations)
    )
    citation_sources = {
        anchor_id: source
        for anchor_id, source in turn.citation_sources.items()
        if anchor_id in valid_anchor_ids
    }
    if len(claims) == len(turn.answer.claims):
        return replace(turn, citation_sources=citation_sources)
    if not claims:
        answer = GroundedAnswer(
            status="insufficient_evidence",
            claims=(),
            message="Prior evidence is no longer available to your current access.",
        )
    else:
        answer = GroundedAnswer(
            status="partial",
            claims=claims,
            message="Some prior evidence is no longer available to your current access.",
        )
    return replace(turn, answer=answer, citation_sources=citation_sources)
