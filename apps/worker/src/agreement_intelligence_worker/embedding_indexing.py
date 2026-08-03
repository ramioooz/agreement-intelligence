from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from time import sleep
from typing import Protocol

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
from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob
from agreement_intelligence_worker.vector_types import Vector


class EmbeddingGateway(Protocol):
    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...


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
            chunks = self._active_unembedded_chunks(connection, job)
            for batch in _batches(chunks, self._configuration.batch_size):
                self._embed_batch(connection, job, batch)

    def _active_unembedded_chunks(self, connection: Connection, job: ProcessingJob) -> list[_Chunk]:
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
        self, connection: Connection, job: ProcessingJob, batch: Sequence[_Chunk]
    ) -> None:
        now = datetime.now(UTC)
        if self._gateway is None:
            self._replace_batch(
                connection,
                job,
                batch,
                now=now,
                vectors=None,
                provenance=None,
                state="unavailable",
                failure_reason="embedding_provider_unconfigured",
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
                        model=self._configuration.model,
                        dimensions=self._configuration.dimensions,
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
            self._replace_batch(
                connection,
                job,
                batch,
                now=now,
                vectors=None,
                provenance=None,
                state="unavailable",
                failure_reason=failure_reason or "embedding_provider_unavailable",
            )
            return
        if len(response.vectors) != len(batch) or any(
            len(vector) != self._configuration.dimensions for vector in response.vectors
        ):
            self._replace_batch(
                connection,
                job,
                batch,
                now=now,
                vectors=None,
                provenance=response.provenance,
                state="failed",
                failure_reason="embedding_dimension_mismatch",
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
        "configuration_version": (
            provenance.configuration_version
            if provenance is not None
            else configuration.configuration_version
        ),
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
