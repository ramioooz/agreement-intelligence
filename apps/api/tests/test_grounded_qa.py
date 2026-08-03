from uuid import uuid4

from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.models import Base
from agreement_intelligence_api.qa.repository import SQLAlchemyQuestionRepository
from agreement_intelligence_api.qa.schemas import CreateQuestionThreadRequest
from agreement_intelligence_api.qa.service import GroundedQuestionService
from agreement_intelligence_api.search.schemas import (
    SearchCitation,
    SearchIndexProvenance,
    SearchNavigation,
    SearchResponse,
    SearchResult,
)
from agreement_intelligence_worker.evidence_validation import (
    AnswerCandidate,
    Citation,
    GroundedClaim,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


class _Identity:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed

    def can_access_workspace(self, *_: object, **__: object) -> bool:
        return self.allowed


class _Search:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, *_: object, **__: object) -> SearchResponse:
        self.calls += 1
        agreement_id = uuid4()
        return SearchResponse(
            limit=20,
            items=[
                SearchResult(
                    agreement_id=agreement_id,
                    agreement_title="Master agreement",
                    agreement_type="client_agreement",
                    agreement_status="active",
                    content_preview="Termination is permitted after material breach.",
                    citation=SearchCitation(
                        chunk_id="term-1",
                        anchor_ids=["source:page:1:block:1"],
                        source_checksum="sha256:source",
                        source_version="sha256:source",
                    ),
                    navigation=SearchNavigation(
                        agreement_id=agreement_id,
                        anchor_ids=["source:page:1:block:1"],
                    ),
                    lexical_rank=1,
                    semantic_rank=None,
                    fused_score=0.1,
                    index_provenance=SearchIndexProvenance(
                        build_id=uuid4(),
                        chunker_version="v1",
                        source_checksum="sha256:source",
                    ),
                )
            ],
        )


def test_new_turn_retrieves_fresh_evidence_and_persists_a_cited_answer() -> None:
    search = _Search()
    service = GroundedQuestionService(
        search=search,
        identity=_Identity(),
        answerer=lambda _: AnswerCandidate(
            claims=(
                GroundedClaim(
                    text="Termination is permitted after material breach.",
                    citations=(
                        Citation(
                            anchor_id="source:page:1:block:1",
                            supporting_quote="Termination is permitted after material breach.",
                        ),
                    ),
                ),
            )
        ),
    )

    thread = service.create_thread(
        Principal(user_id=uuid4()), organization_id=uuid4(), workspace_id=uuid4()
    )
    turn = service.ask(
        Principal(user_id=uuid4()),
        thread=thread,
        question="When may termination occur?",
    )

    assert search.calls == 1
    assert turn.answer.status == "answered"
    assert turn.answer.claims[0].citations[0].anchor_id == "source:page:1:block:1"
    view = service.read_thread(Principal(user_id=uuid4()), thread=thread)
    assert view is not None
    assert view.turns == (turn,)


def test_revoked_workspace_access_cannot_reuse_a_persisted_thread() -> None:
    identity = _Identity()
    service = GroundedQuestionService(
        search=_Search(), identity=identity, answerer=lambda _: AnswerCandidate(claims=())
    )
    principal = Principal(user_id=uuid4())
    thread = service.create_thread(principal, organization_id=uuid4(), workspace_id=uuid4())

    identity.allowed = False

    assert service.read_thread(principal, thread=thread) is None


def test_question_thread_request_limits_portfolio_filters() -> None:
    request = CreateQuestionThreadRequest(agreement_ids=[uuid4()])

    assert request.agreement_ids is not None
    assert len(request.agreement_ids) == 1


def test_only_prior_validated_claims_are_supplied_as_conversation_context() -> None:
    seen_context: list[tuple[str, ...]] = []
    service = GroundedQuestionService(
        search=_Search(),
        identity=_Identity(),
        answerer=lambda request: _record_answer(seen_context, request.conversation_context),
    )
    principal = Principal(user_id=uuid4())
    thread = service.create_thread(principal, organization_id=uuid4(), workspace_id=uuid4())
    service.ask(principal, thread=thread, question="First question")
    service.ask(principal, thread=thread, question="Second question")

    assert seen_context[0] == ()
    assert seen_context[1] == ("Termination is permitted after material breach.",)


def _record_answer(
    seen_context: list[tuple[str, ...]], context: tuple[str, ...]
) -> AnswerCandidate:
    seen_context.append(context)
    return AnswerCandidate(
        claims=(
            GroundedClaim(
                text="Termination is permitted after material breach.",
                citations=(
                    Citation(
                        anchor_id="source:page:1:block:1",
                        supporting_quote="Termination is permitted after material breach.",
                    ),
                ),
            ),
        )
    )


def test_persisted_thread_reloads_its_cited_turns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session: Session = sessionmaker(bind=engine)()
    repository = SQLAlchemyQuestionRepository(session)
    service = GroundedQuestionService(
        search=_Search(),
        identity=_Identity(),
        repository=repository,
        answerer=lambda _: AnswerCandidate(
            claims=(
                GroundedClaim(
                    text="Termination is permitted after material breach.",
                    citations=(
                        Citation(
                            anchor_id="source:page:1:block:1",
                            supporting_quote="Termination is permitted after material breach.",
                        ),
                    ),
                ),
            )
        ),
    )
    principal = Principal(user_id=uuid4())
    thread = service.create_thread(principal, organization_id=uuid4(), workspace_id=uuid4())
    service.ask(principal, thread=thread, question="When may termination occur?")
    session.commit()
    reloaded = GroundedQuestionService(
        search=_Search(),
        identity=_Identity(),
        repository=repository,
        answerer=lambda _: AnswerCandidate(claims=()),
    ).read_thread(principal, thread=thread)

    assert reloaded is not None
    assert reloaded.turns[0].answer.claims[0].citations[0].anchor_id == "source:page:1:block:1"
