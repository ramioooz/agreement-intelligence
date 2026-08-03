from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchCitation(BaseModel):
    chunk_id: str
    anchor_ids: list[str]
    source_checksum: str
    source_version: str


class SearchNavigation(BaseModel):
    agreement_id: UUID
    anchor_ids: list[str]


class SearchIndexProvenance(BaseModel):
    build_id: UUID
    chunker_version: str
    source_checksum: str
    embedding_index_version: str | None = None


class SearchResult(BaseModel):
    agreement_id: UUID
    agreement_title: str
    agreement_type: str
    agreement_status: str
    content_preview: str
    citation: SearchCitation
    navigation: SearchNavigation
    lexical_rank: int | None
    semantic_rank: int | None
    fused_score: float
    index_provenance: SearchIndexProvenance


class SearchResponse(BaseModel):
    items: list[SearchResult]
    limit: int


class SearchFilters(BaseModel):
    """Caller-supplied filters after FastAPI has validated their shape."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1, max_length=500)
    agreement_type: str | None = Field(default=None, max_length=100)
    party: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=32)
    updated_after: datetime | None = None
    updated_before: datetime | None = None
    source_version: str | None = Field(default=None, max_length=255)
    agreement_ids: tuple[UUID, ...] | None = None
