from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agreement_intelligence_worker.model_gateway import (
    EmbeddingConfiguration,
    EmbeddingRequest,
    EmbeddingResponse,
)

from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.search.schemas import (
    SearchCitation,
    SearchFilters,
    SearchIndexProvenance,
    SearchNavigation,
    SearchResponse,
    SearchResult,
)

RRF_K = 60
MAX_CANDIDATES_PER_CHANNEL = 50
DEFAULT_RESULT_LIMIT = 20
MAX_RESULT_LIMIT = 50


@dataclass(frozen=True)
class RankedChunk:
    """Authorized retrieval evidence returned by one ranking channel."""

    chunk_id: str
    agreement_id: UUID
    agreement_title: str
    agreement_type: str
    agreement_status: str
    source_checksum: str
    chunker_version: str
    build_id: UUID
    anchor_ids: tuple[str, ...]
    content: str
    embedding_index_version: str | None = None


@dataclass(frozen=True)
class FusedChunk:
    chunk: RankedChunk
    lexical_rank: int | None
    semantic_rank: int | None
    fused_score: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id


class SearchRepository(Protocol):
    def lexical_candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int,
    ) -> list[RankedChunk]: ...


class SemanticCandidateProvider(Protocol):
    """Extension boundary implemented by the embeddings story.

    Providers must return only evidence already constrained to the supplied
    organization and workspace.  A provider failure is represented by an
    empty list so lexical retrieval stays available.
    """

    def candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int,
    ) -> list[RankedChunk]: ...


class EmbeddingQueryGateway(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...


class SemanticSearchRepository(Protocol):
    def semantic_candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        query_embedding: list[float],
        index_version: str,
        dimensions: int,
        limit: int,
    ) -> list[RankedChunk]: ...


class SQLAlchemySemanticCandidateProvider:
    """Embed the query then retrieve ready vectors from one active index space."""

    def __init__(
        self,
        repository: SemanticSearchRepository,
        *,
        gateway: EmbeddingQueryGateway | None,
        configuration: EmbeddingConfiguration,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._configuration = configuration

    def candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int,
    ) -> list[RankedChunk]:
        if self._gateway is None:
            return []
        response = self._gateway.embed(
            EmbeddingRequest(
                inputs=(filters.query,),
                model=self._configuration.model,
                dimensions=self._configuration.dimensions,
            )
        )
        if len(response.vectors) != 1 or len(response.vectors[0]) != self._configuration.dimensions:
            return []
        return self._repository.semantic_candidates(
            organization_id=organization_id,
            workspace_id=workspace_id,
            filters=filters,
            query_embedding=response.vectors[0],
            index_version=self._configuration.index_version,
            dimensions=self._configuration.dimensions,
            limit=limit,
        )


class UnavailableSemanticCandidateProvider:
    """Safe default until an embedding/vector implementation is configured."""

    def candidates(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int,
    ) -> list[RankedChunk]:
        return []


class SearchNotAuthorizedError(Exception):
    pass


class HybridSearchService:
    def __init__(
        self,
        repository: SearchRepository,
        identity: IdentityService,
        semantic_provider: SemanticCandidateProvider | None = None,
    ) -> None:
        self._repository = repository
        self._identity = identity
        self._semantic_provider = semantic_provider or UnavailableSemanticCandidateProvider()

    def search(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        filters: SearchFilters,
        limit: int = DEFAULT_RESULT_LIMIT,
    ) -> SearchResponse:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.SEARCH_QUERY,
        ):
            raise SearchNotAuthorizedError

        result_limit = min(limit, MAX_RESULT_LIMIT)
        lexical = self._repository.lexical_candidates(
            organization_id=organization_id,
            workspace_id=workspace_id,
            filters=filters,
            limit=MAX_CANDIDATES_PER_CHANNEL,
        )
        try:
            semantic = self._semantic_provider.candidates(
                organization_id=organization_id,
                workspace_id=workspace_id,
                filters=filters,
                limit=MAX_CANDIDATES_PER_CHANNEL,
            )
        except Exception:
            # A vector provider is an enhancement, not an availability
            # dependency for authorized portfolio search.
            semantic = []

        return SearchResponse(
            items=[
                _to_result(item) for item in fuse_reciprocal_rank(lexical, semantic, result_limit)
            ],
            limit=result_limit,
        )


def fuse_reciprocal_rank(
    lexical: list[RankedChunk], semantic: list[RankedChunk], limit: int
) -> list[FusedChunk]:
    """Fuse pre-ranked lexical and semantic results with deterministic RRF."""

    fused: dict[tuple[UUID, UUID, str], FusedChunk] = {}
    for channel, candidates in (("lexical", lexical), ("semantic", semantic)):
        for rank, chunk in enumerate(candidates, start=1):
            key = (chunk.agreement_id, chunk.build_id, chunk.chunk_id)
            prior = fused.get(key)
            lexical_rank = rank if channel == "lexical" else (prior.lexical_rank if prior else None)
            semantic_rank = (
                rank if channel == "semantic" else (prior.semantic_rank if prior else None)
            )
            fused[key] = FusedChunk(
                chunk=chunk,
                lexical_rank=lexical_rank,
                semantic_rank=semantic_rank,
                fused_score=(prior.fused_score if prior else 0.0) + (1.0 / (RRF_K + rank)),
            )
    return sorted(
        fused.values(),
        key=lambda item: (
            -item.fused_score,
            item.lexical_rank if item.lexical_rank is not None else MAX_CANDIDATES_PER_CHANNEL + 1,
            item.semantic_rank
            if item.semantic_rank is not None
            else MAX_CANDIDATES_PER_CHANNEL + 1,
            str(item.chunk.agreement_id),
            item.chunk.chunk_id,
        ),
    )[:limit]


def _to_result(item: FusedChunk) -> SearchResult:
    chunk = item.chunk
    anchors = list(chunk.anchor_ids)
    return SearchResult(
        agreement_id=chunk.agreement_id,
        agreement_title=chunk.agreement_title,
        agreement_type=chunk.agreement_type,
        agreement_status=chunk.agreement_status,
        content_preview=chunk.content[:500],
        citation=SearchCitation(
            chunk_id=chunk.chunk_id,
            anchor_ids=anchors,
            source_checksum=chunk.source_checksum,
            source_version=chunk.source_checksum,
        ),
        navigation=SearchNavigation(agreement_id=chunk.agreement_id, anchor_ids=anchors),
        lexical_rank=item.lexical_rank,
        semantic_rank=item.semantic_rank,
        fused_score=item.fused_score,
        index_provenance=SearchIndexProvenance(
            build_id=chunk.build_id,
            chunker_version=chunk.chunker_version,
            source_checksum=chunk.source_checksum,
            embedding_index_version=chunk.embedding_index_version,
        ),
    )
