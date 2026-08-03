from __future__ import annotations

import json
from uuid import uuid4

from agreement_intelligence_worker.document_indexing import (
    SQLAlchemyDocumentIndexSink,
    structural_chunks_from_manifest,
    worker_index_metadata,
)
from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob
from sqlalchemy import create_engine, select


def test_structural_chunks_are_stable_and_keep_heading_context() -> None:
    manifest = _manifest()

    first = structural_chunks_from_manifest(manifest)
    second = structural_chunks_from_manifest(json.loads(json.dumps(manifest)))

    assert first == second
    assert [chunk.heading_path for chunk in first] == [
        ("Master Services Agreement",),
        ("Master Services Agreement", "Term and Termination"),
    ]
    assert first[0].anchor_ids == ("citation-title", "citation-scope")
    assert first[0].chunk_id.startswith("chunk-")
    assert first[0].text == "Master Services Agreement\nScope of services is described below."


def test_reindexing_the_same_manifest_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_index_metadata.create_all(engine)
    job = _job()
    storage = _Storage({"analysis/manifest.json": json.dumps(_manifest()).encode()})
    sink = SQLAlchemyDocumentIndexSink(engine, storage)
    artifact = CompletedArtifact(job_id=job.id, key="analysis/manifest.json")

    sink.completed(job, artifact)
    sink.completed(job, artifact)

    with engine.connect() as connection:
        builds = connection.execute(
            select(worker_index_metadata.tables["retrieval_index_builds"])
        ).all()
        chunks = connection.execute(select(worker_index_metadata.tables["retrieval_chunks"])).all()
    assert len(builds) == 1
    assert builds[0]._mapping["state"] == "active"
    assert len(chunks) == 2


def test_activation_replaces_stale_chunks_only_after_new_build_is_ready() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_index_metadata.create_all(engine)
    job = _job()
    storage = _Storage({"analysis/one.json": json.dumps(_manifest("a" * 64)).encode()})
    sink = SQLAlchemyDocumentIndexSink(engine, storage)

    sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/one.json"))
    storage.objects["analysis/two.json"] = json.dumps(_manifest("b" * 64)).encode()
    sink.completed(job, CompletedArtifact(job_id=job.id, key="analysis/two.json"))

    with engine.connect() as connection:
        builds = connection.execute(
            select(worker_index_metadata.tables["retrieval_index_builds"]).order_by(
                worker_index_metadata.tables["retrieval_index_builds"].c.source_checksum
            )
        ).all()
        chunks = connection.execute(select(worker_index_metadata.tables["retrieval_chunks"])).all()
    assert [row._mapping["state"] for row in builds] == ["stale", "active"]
    assert {row._mapping["source_checksum"] for row in chunks} == {"b" * 64}


class _Storage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def read(self, key: str) -> bytes | None:
        return self.objects.get(key)


def _job() -> ProcessingJob:
    return ProcessingJob(
        id=uuid4(),
        agreement_id=uuid4(),
        state="completed",
        attempt_count=1,
        organization_id=uuid4(),
        workspace_id=uuid4(),
        source_checksum="a" * 64,
    )


def _manifest(checksum: str = "a" * 64) -> dict[str, object]:
    return {
        "schema_version": "document-analysis.v1",
        "source": {"checksum": checksum},
        "document": {
            "pages": [
                {
                    "number": 1,
                    "blocks": [
                        {
                            "anchor_id": "citation-title",
                            "kind": "heading",
                            "text": "Master Services Agreement",
                        },
                        {
                            "anchor_id": "citation-scope",
                            "kind": "paragraph",
                            "text": "Scope of services is described below.",
                        },
                        {
                            "anchor_id": "citation-term",
                            "kind": "heading",
                            "text": "Term and Termination",
                        },
                        {
                            "anchor_id": "citation-notice",
                            "kind": "paragraph",
                            "text": "Either party may terminate on thirty days notice.",
                        },
                    ],
                }
            ]
        },
    }
