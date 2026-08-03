from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from agreement_intelligence_worker.document_indexing import (
    SQLAlchemyDocumentIndexSink,
    structural_chunks_from_manifest,
    worker_index_metadata,
)
from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError


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


def test_identical_manifest_chunks_are_scoped_by_agreement_without_changing_identity() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_index_metadata.create_all(engine)
    first_job = _job()
    second_job = _job(
        organization_id=first_job.organization_id, workspace_id=first_job.workspace_id
    )
    storage = _Storage({"analysis/manifest.json": json.dumps(_manifest()).encode()})
    sink = SQLAlchemyDocumentIndexSink(engine, storage)

    sink.completed(first_job, CompletedArtifact(job_id=first_job.id, key="analysis/manifest.json"))
    sink.completed(
        second_job, CompletedArtifact(job_id=second_job.id, key="analysis/manifest.json")
    )

    with engine.connect() as connection:
        chunks = connection.execute(select(worker_index_metadata.tables["retrieval_chunks"])).all()

    assert len(chunks) == 4
    by_agreement = {row._mapping["agreement_id"]: row._mapping["chunk_id"] for row in chunks}
    assert len(by_agreement) == 2
    assert len(set(by_agreement.values())) == 1


def test_only_one_active_build_can_exist_for_an_agreement() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    worker_index_metadata.create_all(engine)
    job = _job()
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    first_build_id = uuid4()
    values = {
        "organization_id": job.organization_id,
        "workspace_id": job.workspace_id,
        "agreement_id": job.agreement_id,
        "chunker_version": "structure-aware.v1",
        "state": "active",
        "created_at": now,
        "activated_at": now,
    }

    with engine.begin() as connection:
        connection.execute(
            insert(worker_index_metadata.tables["retrieval_index_builds"]).values(
                id=first_build_id,
                source_checksum="a" * 64,
                **values,
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                insert(worker_index_metadata.tables["retrieval_index_builds"]).values(
                    id=uuid4(),
                    source_checksum="b" * 64,
                    **values,
                )
            )


def test_structural_groups_split_at_token_limit_with_overlap() -> None:
    paragraph_one = " ".join(f"first-{index}" for index in range(600))
    paragraph_two = " ".join(f"second-{index}" for index in range(600))
    manifest = _manifest_with_blocks(
        [
            {"anchor_id": "citation-title", "kind": "heading", "text": "Liability"},
            {"anchor_id": "citation-one", "kind": "paragraph", "text": paragraph_one},
            {"anchor_id": "citation-two", "kind": "paragraph", "text": paragraph_two},
        ]
    )

    chunks = structural_chunks_from_manifest(manifest)

    assert len(chunks) == 2
    assert all(len(chunk.text.split()) <= 1_000 for chunk in chunks)
    assert chunks[0].text.split()[-100:] == chunks[1].text.split()[:100]
    assert chunks[0].heading_path == chunks[1].heading_path == ("Liability",)


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


def _job(*, organization_id: UUID | None = None, workspace_id: UUID | None = None) -> ProcessingJob:
    return ProcessingJob(
        id=uuid4(),
        agreement_id=uuid4(),
        state="completed",
        attempt_count=1,
        organization_id=organization_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        source_checksum="a" * 64,
    )


def _manifest(checksum: str = "a" * 64) -> dict[str, object]:
    return _manifest_with_blocks(
        [
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
        checksum=checksum,
    )


def _manifest_with_blocks(
    blocks: list[dict[str, str]], checksum: str = "a" * 64
) -> dict[str, object]:
    return {
        "schema_version": "document-analysis.v1",
        "source": {"checksum": checksum},
        "document": {
            "pages": [
                {
                    "number": 1,
                    "blocks": blocks,
                }
            ]
        },
    }
