from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from time import sleep
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    delete,
    select,
)
from sqlalchemy.engine import Connection, Engine

from agreement_intelligence_worker.ai_configuration import (
    AIOperation,
    ResolvedAIConfiguration,
    model_for_route,
    resolve_configuration,
    resolve_configuration_by_id,
)
from agreement_intelligence_worker.document_indexing import (
    retrieval_chunks,
    retrieval_index_builds,
    worker_index_metadata,
)
from agreement_intelligence_worker.model_gateway import (
    EmbeddingConfiguration,
    EmbeddingRequest,
    EmbeddingResponse,
    GatewayProvenance,
    GatewayResponseError,
    GatewayUnavailableError,
)
from agreement_intelligence_worker.processing import (
    CompletedArtifact,
    CompletionHandler,
    ProcessingJob,
    TransientProcessingError,
)
from agreement_intelligence_worker.vector_types import Vector


class EmbeddingGateway(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...


_EMBEDDING_REINDEX_PROFILE_PREFIX = "embedding-reindex:"


def embedding_reindex_configuration_id(profile: str | None) -> UUID | None:
    if profile is None or not profile.startswith(_EMBEDDING_REINDEX_PROFILE_PREFIX):
        return None
    try:
        return UUID(profile.removeprefix(_EMBEDDING_REINDEX_PROFILE_PREFIX))
    except ValueError:
        return None


@dataclass(frozen=True)
class EmbeddingReindexCompletionHandler:
    normal: CompletionHandler
    embeddings: CompletionHandler

    def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
        if embedding_reindex_configuration_id(job.profile) is not None:
            self.embeddings.completed(job, artifact)
            return
        self.normal.completed(job, artifact)


def _endpoint_mode(gateway: EmbeddingGateway) -> str:
    """Use the gateway's declared provider; lightweight test gateways default to OpenAI."""

    configuration = getattr(gateway, "configuration", None)
    mode = getattr(configuration, "mode", "openai")
    if mode not in {"openai", "openai-compatible"}:
        raise ValueError("unsupported embedding gateway endpoint mode")
    return str(mode)


embedding_metadata = worker_index_metadata
retrieval_chunk_embeddings = Table(
    "retrieval_chunk_embeddings",
    embedding_metadata,
    Column("organization_id", retrieval_chunks.c.organization_id.type, nullable=False),
    Column("workspace_id", retrieval_chunks.c.workspace_id.type, nullable=False),
    Column("agreement_id", retrieval_chunks.c.agreement_id.type, nullable=False),
    Column("build_id", retrieval_chunks.c.build_id.type, nullable=False),
    Column("chunk_id", String(80), nullable=False),
    Column("index_version", String(100), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("embedding", Vector(), nullable=True),
    Column("state", String(32), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(256), nullable=False),
    Column("configuration_version", String(100), nullable=False),
    Column("input_tokens", Integer, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("retry_outcome", String(64), nullable=False),
    Column("fallback_outcome", String(64), nullable=False),
    Column("failure_reason", String(100), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "agreement_id",
        "build_id",
        "chunk_id",
        "index_version",
        "dimensions",
        name="pk_retrieval_chunk_embeddings",
    ),
    Index(
        "ix_retrieval_chunk_embeddings_scope_ready",
        "organization_id",
        "workspace_id",
        "agreement_id",
        "index_version",
        "dimensions",
        "state",
    ),
)


@dataclass(frozen=True)
class _Chunk:
    chunk_id: str
    content: str
    build_id: object


class SQLAlchemyEmbeddingIndexSink:
    """Embeds active canonical chunks without allowing provider failure to fail processing."""

    def __init__(
        self,
        engine: Engine,
        *,
        gateway: EmbeddingGateway | None,
        configuration: EmbeddingConfiguration,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._engine = engine
        self._gateway = gateway
        self._configuration = configuration
        self._sleeper = sleeper

    def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
        del artifact
        if job.organization_id is None or job.workspace_id is None:
            raise ValueError("Embedding index requires tenant scope")
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql(
                    "SELECT set_config('app.organization_id', %s, true)",
                    (str(job.organization_id),),
                )
            configuration_id = embedding_reindex_configuration_id(job.profile)
            active_configuration = (
                resolve_configuration_by_id(
                    AIOperation.EMBEDDING,
                    configuration_id,
                    organization_id=job.organization_id,
                    workspace_id=job.workspace_id,
                )
                if configuration_id is not None
                else resolve_configuration(
                    AIOperation.EMBEDDING,
                    os.environ.get("AI_CONFIGURATION_ENVIRONMENT", "local"),
                    organization_id=job.organization_id,
                    workspace_id=job.workspace_id,
                )
            )
            if active_configuration is None:
                raise ValueError("Embedding reindex configuration is unavailable in tenant scope")
            active_model = (
                model_for_route(
                    active_configuration,
                    self._configuration.model,
                    endpoint_mode=_endpoint_mode(self._gateway),
                )
                if self._gateway is not None
                else self._configuration.model
            )
            chunks = self._active_unembedded_chunks(
                connection,
                job,
                configuration_version=active_configuration.version,
                model=active_model,
            )
            for batch in _batches(chunks, self._configuration.batch_size):
                self._embed_batch(connection, job, batch, active_configuration)

    def _active_unembedded_chunks(
        self,
        connection: Connection,
        job: ProcessingJob,
        *,
        configuration_version: str,
        model: str,
    ) -> list[_Chunk]:
        embedded = retrieval_chunk_embeddings.alias("embedded")
        query = (
            select(
                retrieval_chunks.c.chunk_id,
                retrieval_chunks.c.content,
                retrieval_chunks.c.build_id,
            )
            .join(
                retrieval_index_builds,
                retrieval_chunks.c.build_id == retrieval_index_builds.c.id,
            )
            .outerjoin(
                embedded,
                (embedded.c.agreement_id == retrieval_chunks.c.agreement_id)
                & (embedded.c.build_id == retrieval_chunks.c.build_id)
                & (embedded.c.chunk_id == retrieval_chunks.c.chunk_id)
                & (embedded.c.index_version == self._configuration.index_version)
                & (embedded.c.dimensions == self._configuration.dimensions)
                & (embedded.c.configuration_version == configuration_version)
                & (embedded.c.model == model)
                & (embedded.c.state == "ready"),
            )
            .where(
                retrieval_chunks.c.organization_id == job.organization_id,
                retrieval_chunks.c.workspace_id == job.workspace_id,
                retrieval_chunks.c.agreement_id == job.agreement_id,
                retrieval_index_builds.c.state == "active",
                embedded.c.chunk_id.is_(None),
            )
            .order_by(retrieval_chunks.c.ordinal)
        )
        return [
            _Chunk(chunk_id=row.chunk_id, content=row.content, build_id=row.build_id)
            for row in connection.execute(query)
        ]

    def _embed_batch(
        self,
        connection: Connection,
        job: ProcessingJob,
        batch: Sequence[_Chunk],
        active_configuration: ResolvedAIConfiguration,
    ) -> None:
        now = datetime.now(UTC)
        if self._gateway is None:
            if embedding_reindex_configuration_id(job.profile) is not None:
                raise TransientProcessingError("Embedding provider is unavailable")
            self._replace_batch(
                connection,
                job,
                batch,
                now=now,
                vectors=None,
                provenance=None,
                state="unavailable",
                failure_reason="embedding_provider_unconfigured",
                active_configuration=active_configuration,
            )
            return
        response: EmbeddingResponse | None = None
        failure_reason: str | None = None
        attempts = 0
        while attempts <= self._configuration.max_retries:
            attempts += 1
            try:
                response = self._gateway.embed(
                    EmbeddingRequest(
                        inputs=tuple(chunk.content for chunk in batch),
                        model=model_for_route(
                            active_configuration,
                            self._configuration.model,
                            endpoint_mode=_endpoint_mode(self._gateway),
                        ),
                        dimensions=self._configuration.dimensions,
                        resolved_configuration=active_configuration,
                    )
                )
                break
            except GatewayUnavailableError as error:
                failure_reason = error.safe_reason
                if attempts <= self._configuration.max_retries:
                    self._sleeper(0.1 * attempts)
            except GatewayResponseError:
                failure_reason = "embedding_response_invalid"
                break
        if response is None:
            if embedding_reindex_configuration_id(job.profile) is not None:
                raise TransientProcessingError("Embedding provider is unavailable")
            self._replace_batch(
                connection,
                job,
                batch,
                now=now,
                vectors=None,
                provenance=None,
                state="unavailable",
                failure_reason=failure_reason or "embedding_provider_unavailable",
                active_configuration=active_configuration,
            )
            return
        if len(response.vectors) != len(batch) or any(
            len(vector) != self._configuration.dimensions for vector in response.vectors
        ):
            if embedding_reindex_configuration_id(job.profile) is not None:
                raise TransientProcessingError("Embedding response is invalid")
            self._replace_batch(
                connection,
                job,
                batch,
                now=now,
                vectors=None,
                provenance=response.provenance,
                state="failed",
                failure_reason="embedding_dimension_mismatch",
                active_configuration=active_configuration,
            )
            return
        self._replace_batch(
            connection,
            job,
            batch,
            now=now,
            vectors=response.vectors,
            provenance=response.provenance,
            state="ready",
            failure_reason=None,
            active_configuration=active_configuration,
        )

    def _replace_batch(
        self,
        connection: Connection,
        job: ProcessingJob,
        batch: Sequence[_Chunk],
        *,
        now: datetime,
        vectors: list[list[float]] | None,
        provenance: GatewayProvenance | None,
        state: str,
        failure_reason: str | None,
        active_configuration: ResolvedAIConfiguration,
    ) -> None:
        for position, chunk in enumerate(batch):
            connection.execute(
                delete(retrieval_chunk_embeddings).where(
                    retrieval_chunk_embeddings.c.organization_id == job.organization_id,
                    retrieval_chunk_embeddings.c.workspace_id == job.workspace_id,
                    retrieval_chunk_embeddings.c.agreement_id == job.agreement_id,
                    retrieval_chunk_embeddings.c.build_id == chunk.build_id,
                    retrieval_chunk_embeddings.c.chunk_id == chunk.chunk_id,
                    retrieval_chunk_embeddings.c.index_version == self._configuration.index_version,
                    retrieval_chunk_embeddings.c.dimensions == self._configuration.dimensions,
                )
            )
            vector = vectors[position] if vectors is not None else None
            values = _embedding_values(
                job,
                chunk,
                configuration=self._configuration,
                vector=vector,
                provenance=provenance,
                state=state,
                failure_reason=failure_reason,
                now=now,
                batch_size=len(batch),
                active_configuration=active_configuration,
            )
            connection.execute(retrieval_chunk_embeddings.insert().values(**values))


def _embedding_values(
    job: ProcessingJob,
    chunk: _Chunk,
    *,
    configuration: EmbeddingConfiguration,
    vector: list[float] | None,
    provenance: GatewayProvenance | None,
    state: str,
    failure_reason: str | None,
    now: datetime,
    batch_size: int,
    active_configuration: ResolvedAIConfiguration,
) -> dict[str, object]:
    token_share = (
        ceil(provenance.input_tokens / batch_size)
        if provenance is not None and provenance.input_tokens is not None
        else None
    )
    cost = (
        round(token_share * configuration.input_cost_per_million_tokens / 1_000_000, 12)
        if token_share is not None
        else None
    )
    return {
        "organization_id": job.organization_id,
        "workspace_id": job.workspace_id,
        "agreement_id": job.agreement_id,
        "build_id": chunk.build_id,
        "chunk_id": chunk.chunk_id,
        "index_version": configuration.index_version,
        "dimensions": configuration.dimensions,
        "embedding": vector,
        "state": state,
        "provider": provenance.provider if provenance is not None else "unconfigured",
        "model": provenance.model if provenance is not None else configuration.model,
        "configuration_version": active_configuration.version,
        "input_tokens": token_share,
        "latency_ms": provenance.latency_ms if provenance is not None else None,
        "cost_usd": cost,
        "retry_outcome": provenance.retry_outcome if provenance is not None else "not_attempted",
        "fallback_outcome": provenance.fallback_outcome
        if provenance is not None
        else "not_attempted",
        "failure_reason": failure_reason,
        "created_at": now,
        "updated_at": now,
    }


def _batches(chunks: Sequence[_Chunk], size: int) -> list[Sequence[_Chunk]]:
    return [chunks[offset : offset + size] for offset in range(0, len(chunks), size)]
