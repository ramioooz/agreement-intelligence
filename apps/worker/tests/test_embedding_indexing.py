from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from _pytest.monkeypatch import MonkeyPatch
from agreement_intelligence_worker.ai_configuration import AIOperation, ConfigurationSnapshot
from agreement_intelligence_worker.embedding_indexing import (
    EmbeddingReindexCompletionHandler,
    SQLAlchemyEmbeddingIndexSink,
    embedding_metadata,
)
from agreement_intelligence_worker.model_gateway import (
    EmbeddingConfiguration,
    EmbeddingRequest,
    EmbeddingResponse,
    GatewayProvenance,
    GatewayUnavailableError,
)
from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob
from sqlalchemy import create_engine, insert, select
from sqlalchemy.engine import Engine


def test_embedding_sink_batches_active_chunks_and_records_provenance() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    embedding_metadata.create_all(engine)
    job, build_id = _insert_active_chunks(engine, count=3)
    gateway = _Gateway(vectors=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
    sink = SQLAlchemyEmbeddingIndexSink(
        engine,
        gateway=gateway,
        configuration=EmbeddingConfiguration(
            model="embedding-model",
            dimensions=2,
            index_version="embedding-v1",
            batch_size=2,
            max_retries=0,
            configuration_version="embedding-gateway.v1",
            input_cost_per_million_tokens=0.02,
        ),
    )

    sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/manifest.json"))

    assert [request.inputs for request in gateway.requests] == [
        ("chunk 0", "chunk 1"),
        ("chunk 2",),
    ]
    assert all(request.dimensions == 2 for request in gateway.requests)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(embedding_metadata.tables["retrieval_chunk_embeddings"])
                .where(
                    embedding_metadata.tables["retrieval_chunk_embeddings"].c.build_id == build_id
                )
                .order_by(embedding_metadata.tables["retrieval_chunk_embeddings"].c.chunk_id)
            )
            .mappings()
            .all()
        )
    assert [row["state"] for row in rows] == ["ready", "ready", "ready"]
    assert [row["dimensions"] for row in rows] == [2, 2, 2]
    assert [row["provider"] for row in rows] == ["openai", "openai", "openai"]
    assert all(row["index_version"] == "embedding-v1" for row in rows)
    assert all(row["embedding"] is not None for row in rows)


def test_embedding_sink_retries_an_unavailable_provider_and_keeps_lexical_fallback_available() -> (
    None
):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    embedding_metadata.create_all(engine)
    job, _ = _insert_active_chunks(engine, count=1)
    gateway = _UnavailableGateway()
    sink = SQLAlchemyEmbeddingIndexSink(
        engine,
        gateway=gateway,
        configuration=EmbeddingConfiguration(
            model="embedding-model",
            dimensions=2,
            index_version="embedding-v1",
            batch_size=2,
            max_retries=2,
            configuration_version="embedding-gateway.v1",
            input_cost_per_million_tokens=0.02,
        ),
        sleeper=lambda _: None,
    )

    sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/manifest.json"))

    assert gateway.attempts == 3
    with engine.connect() as connection:
        row = (
            connection.execute(select(embedding_metadata.tables["retrieval_chunk_embeddings"]))
            .mappings()
            .one()
        )
    assert row["state"] == "unavailable"
    assert row["failure_reason"] == "endpoint_retryable_response"
    assert row["embedding"] is None


def test_embedding_sink_records_unconfigured_provider_without_blocking_indexing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    embedding_metadata.create_all(engine)
    job, _ = _insert_active_chunks(engine, count=1)
    sink = SQLAlchemyEmbeddingIndexSink(
        engine,
        gateway=None,
        configuration=EmbeddingConfiguration(
            model="embedding-model",
            dimensions=2,
            index_version="embedding-v1",
            batch_size=2,
            max_retries=0,
            configuration_version="embedding-gateway.v1",
            input_cost_per_million_tokens=0.02,
        ),
    )

    sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/manifest.json"))

    with engine.connect() as connection:
        row = (
            connection.execute(select(embedding_metadata.tables["retrieval_chunk_embeddings"]))
            .mappings()
            .one()
        )
    assert row["state"] == "unavailable"
    assert row["failure_reason"] == "embedding_provider_unconfigured"


def test_embedding_sink_keeps_dimension_versions_isolated() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    embedding_metadata.create_all(engine)
    job, _ = _insert_active_chunks(engine, count=1)

    for dimensions, vector in ((2, [0.1, 0.2]), (3, [0.1, 0.2, 0.3])):
        sink = SQLAlchemyEmbeddingIndexSink(
            engine,
            gateway=_Gateway(vectors=[vector]),
            configuration=EmbeddingConfiguration(
                model="embedding-model",
                dimensions=dimensions,
                index_version="embedding-v1",
                batch_size=2,
                max_retries=0,
                configuration_version="embedding-gateway.v1",
                input_cost_per_million_tokens=0.02,
            ),
        )
        sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/manifest.json"))

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(embedding_metadata.tables["retrieval_chunk_embeddings"]).order_by(
                    embedding_metadata.tables["retrieval_chunk_embeddings"].c.dimensions
                )
            )
            .mappings()
            .all()
        )
    assert [row["dimensions"] for row in rows] == [2, 3]
    assert [row["state"] for row in rows] == ["ready", "ready"]


def test_embedding_promotion_replaces_vectors_in_the_exact_active_configuration_space(
    monkeypatch: MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    embedding_metadata.create_all(engine)
    job, _ = _insert_active_chunks(engine, count=1)
    configuration_id = uuid4()
    active = _configuration_snapshot(version="3.0.0", model="embedding-model-v3")
    target = _configuration_snapshot(version="2.0.0", model="embedding-model-v2")
    monkeypatch.setattr(
        "agreement_intelligence_worker.embedding_indexing.resolve_configuration",
        lambda *_args, **_kwargs: active,
    )
    monkeypatch.setattr(
        "agreement_intelligence_worker.embedding_indexing.resolve_configuration_by_id",
        lambda _operation, target_id, **_kwargs: target if target_id == configuration_id else None,
        raising=False,
    )
    gateway = _Gateway(vectors=[[0.8, 0.9]])
    sink = SQLAlchemyEmbeddingIndexSink(
        engine,
        gateway=gateway,
        configuration=_embedding_configuration(),
    )
    job = ProcessingJob(
        **{
            **job.__dict__,
            "profile": f"embedding-reindex:{configuration_id}",
        }
    )

    sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/manifest.json"))

    assert [request.model for request in gateway.requests] == ["embedding-model-v2"]
    with engine.connect() as connection:
        row = (
            connection.execute(select(embedding_metadata.tables["retrieval_chunk_embeddings"]))
            .mappings()
            .one()
        )
    assert row["configuration_version"] == "2.0.0"
    assert row["model"] == "embedding-model-v2"
    assert list(row["embedding"]) == [0.8, 0.9]


def test_embedding_reindex_completion_bypasses_unrelated_document_handlers() -> None:
    normal = _CompletionRecorder()
    embeddings = _CompletionRecorder()
    handler = EmbeddingReindexCompletionHandler(normal=normal, embeddings=embeddings)
    configuration_id = uuid4()
    reindex_job = ProcessingJob(
        id=uuid4(),
        agreement_id=uuid4(),
        state="completed",
        attempt_count=1,
        profile=f"embedding-reindex:{configuration_id}",
    )
    artifact = CompletedArtifact(job_id=reindex_job.id, key="embedding-reindex/result.json")

    handler.completed(reindex_job, artifact)

    assert normal.calls == []
    assert embeddings.calls == [(reindex_job, artifact)]


@dataclass
class _Gateway:
    vectors: list[list[float]]

    def __post_init__(self) -> None:
        self.requests: list[EmbeddingRequest] = []

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        start = sum(len(item.inputs) for item in self.requests[:-1])
        return EmbeddingResponse(
            vectors=self.vectors[start : start + len(request.inputs)],
            provenance=GatewayProvenance(
                provider="openai",
                endpoint_kind="hosted",
                model=request.model or "embedding-model",
                configuration_version="embedding-gateway.v1",
                latency_ms=12,
                input_tokens=4,
                output_tokens=None,
                total_tokens=4,
                cost_usd=None,
                retry_outcome="not_retried",
                fallback_outcome="not_needed",
                safe_failure_reason=None,
            ),
        )


class _UnavailableGateway:
    def __init__(self) -> None:
        self.attempts = 0

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        del request
        self.attempts += 1
        raise GatewayUnavailableError("endpoint_retryable_response")


class _CompletionRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[ProcessingJob, CompletedArtifact]] = []

    def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
        self.calls.append((job, artifact))


def _embedding_configuration() -> EmbeddingConfiguration:
    return EmbeddingConfiguration(
        model="embedding-model",
        dimensions=2,
        index_version="embedding-v1",
        batch_size=2,
        max_retries=0,
        configuration_version="embedding-gateway.v1",
        input_cost_per_million_tokens=0.02,
    )


def _configuration_snapshot(*, version: str, model: str) -> ConfigurationSnapshot:
    return ConfigurationSnapshot(
        operation=AIOperation.EMBEDDING,
        version=version,
        prompt_template="Embed supplied text.",
        schema={"type": "object"},
        model_route=f"openai:{model}",
        parameters={},
        schema_checksum=f"schema-{version}",
    )


def _insert_active_chunks(engine: Engine, *, count: int) -> tuple[ProcessingJob, object]:
    tables = embedding_metadata.tables
    organization_id = uuid4()
    workspace_id = uuid4()
    agreement_id = uuid4()
    build_id = uuid4()
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(tables["retrieval_index_builds"]).values(
                id=build_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=agreement_id,
                source_checksum="a" * 64,
                chunker_version="structure-aware.v1",
                state="active",
                created_at=now,
                activated_at=now,
            )
        )
        connection.execute(
            insert(tables["retrieval_chunks"]),
            [
                {
                    "chunk_id": f"chunk-{ordinal}",
                    "organization_id": organization_id,
                    "workspace_id": workspace_id,
                    "agreement_id": agreement_id,
                    "build_id": build_id,
                    "source_checksum": "a" * 64,
                    "chunker_version": "structure-aware.v1",
                    "ordinal": ordinal,
                    "heading_path": [],
                    "anchor_ids": [f"anchor-{ordinal}"],
                    "content": f"chunk {ordinal}",
                }
                for ordinal in range(count)
            ],
        )
    return (
        ProcessingJob(
            id=uuid4(),
            agreement_id=agreement_id,
            state="completed",
            attempt_count=1,
            organization_id=organization_id,
            workspace_id=workspace_id,
        ),
        build_id,
    )
