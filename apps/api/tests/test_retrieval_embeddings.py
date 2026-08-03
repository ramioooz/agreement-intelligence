from uuid import uuid4

from agreement_intelligence_api.retrieval.models import RetrievalChunkEmbeddingRecord
from agreement_intelligence_api.retrieval.repository import RetrievalEmbeddingCandidate


def test_embedding_record_keeps_versioned_provenance_and_vector_dimensions() -> None:
    columns = RetrievalChunkEmbeddingRecord.__table__.c

    assert {
        "organization_id",
        "workspace_id",
        "agreement_id",
        "build_id",
        "chunk_id",
        "index_version",
        "dimensions",
        "embedding",
        "provider",
        "model",
        "configuration_version",
        "input_tokens",
        "latency_ms",
        "cost_usd",
        "failure_reason",
    }.issubset(columns.keys())


def test_embedding_candidate_contract_keeps_source_navigation_and_index_identity() -> None:
    candidate = RetrievalEmbeddingCandidate(
        agreement_id=uuid4(),
        build_id=uuid4(),
        chunk_id="chunk-1",
        content="Termination is permitted on notice.",
        anchor_ids=("citation-1",),
        embedding=[0.1, 0.2],
        index_version="embedding-v1",
        dimensions=2,
    )

    assert candidate.anchor_ids == ("citation-1",)
    assert candidate.index_version == "embedding-v1"
