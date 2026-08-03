from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    delete,
    select,
    text,
    update,
)

from agreement_intelligence_worker.processing import CompletedArtifact, ProcessingJob

STRUCTURE_AWARE_CHUNKER_VERSION = "structure-aware.v1"
MAX_CHUNK_TOKENS = 1_000
CHUNK_OVERLAP_TOKENS = 100


@dataclass(frozen=True)
class RetrievalChunk:
    chunk_id: str
    ordinal: int
    heading_path: tuple[str, ...]
    anchor_ids: tuple[str, ...]
    text: str


class ArtifactStorage(Protocol):
    def read(self, key: str) -> bytes | None: ...


worker_index_metadata = MetaData()
retrieval_index_builds = Table(
    "retrieval_index_builds",
    worker_index_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("source_checksum", String(255), nullable=False),
    Column("chunker_version", String(100), nullable=False),
    Column("state", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("activated_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "id",
        "organization_id",
        "workspace_id",
        "agreement_id",
        name="uq_retrieval_index_build_scope",
    ),
    Index(
        "uq_retrieval_index_build_source",
        "agreement_id",
        "source_checksum",
        "chunker_version",
        unique=True,
    ),
    Index(
        "ix_retrieval_index_builds_scope_active",
        "organization_id",
        "workspace_id",
        "agreement_id",
        "state",
    ),
    Index(
        "uq_retrieval_index_builds_active_scope",
        "organization_id",
        "workspace_id",
        "agreement_id",
        unique=True,
        sqlite_where=text("state = 'active'"),
        postgresql_where=text("state = 'active'"),
    ),
)
retrieval_chunks = Table(
    "retrieval_chunks",
    worker_index_metadata,
    Column("chunk_id", String(80), nullable=False),
    Column("organization_id", Uuid(as_uuid=True), nullable=False),
    Column("workspace_id", Uuid(as_uuid=True), nullable=False),
    Column("agreement_id", Uuid(as_uuid=True), nullable=False),
    Column("build_id", Uuid(as_uuid=True), nullable=False),
    Column("source_checksum", String(255), nullable=False),
    Column("chunker_version", String(100), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("heading_path", JSON, nullable=False),
    Column("anchor_ids", JSON, nullable=False),
    Column("content", String, nullable=False),
    PrimaryKeyConstraint(
        "agreement_id",
        "build_id",
        "chunk_id",
        name="pk_retrieval_chunks",
    ),
    ForeignKeyConstraint(
        ["build_id", "organization_id", "workspace_id", "agreement_id"],
        [
            "retrieval_index_builds.id",
            "retrieval_index_builds.organization_id",
            "retrieval_index_builds.workspace_id",
            "retrieval_index_builds.agreement_id",
        ],
        name="fk_retrieval_chunks_build_scope",
    ),
    Index(
        "ix_retrieval_chunks_scope_build",
        "organization_id",
        "workspace_id",
        "agreement_id",
        "build_id",
    ),
)


class SQLAlchemyDocumentIndexSink:
    """Builds canonical, structure-aware chunks from an immutable analysis artifact."""

    def __init__(self, engine: Engine, storage: ArtifactStorage) -> None:
        self._engine = engine
        self._storage = storage

    def completed(self, job: ProcessingJob, artifact: CompletedArtifact) -> None:
        if job.organization_id is None or job.workspace_id is None:
            raise ValueError("Document index requires tenant scope")
        manifest = _manifest_from_artifact(self._storage, artifact.key)
        checksum = _source_checksum(manifest)
        chunks = structural_chunks_from_manifest(manifest)
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT set_config('app.organization_id', :organization_id, true)"),
                    {"organization_id": str(job.organization_id)},
                )
            build = (
                connection.execute(
                    select(retrieval_index_builds).where(
                        retrieval_index_builds.c.organization_id == job.organization_id,
                        retrieval_index_builds.c.workspace_id == job.workspace_id,
                        retrieval_index_builds.c.agreement_id == job.agreement_id,
                        retrieval_index_builds.c.source_checksum == checksum,
                        retrieval_index_builds.c.chunker_version == STRUCTURE_AWARE_CHUNKER_VERSION,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if build is not None and build["state"] == "active":
                return
            build_id = cast(UUID, build["id"]) if build is not None else uuid4()
            if build is None:
                connection.execute(
                    retrieval_index_builds.insert().values(
                        id=build_id,
                        organization_id=job.organization_id,
                        workspace_id=job.workspace_id,
                        agreement_id=job.agreement_id,
                        source_checksum=checksum,
                        chunker_version=STRUCTURE_AWARE_CHUNKER_VERSION,
                        state="building",
                        created_at=now,
                        activated_at=None,
                    )
                )
            else:
                connection.execute(
                    delete(retrieval_chunks).where(retrieval_chunks.c.build_id == build_id)
                )
            connection.execute(
                retrieval_chunks.insert(),
                [
                    {
                        "chunk_id": chunk.chunk_id,
                        "organization_id": job.organization_id,
                        "workspace_id": job.workspace_id,
                        "agreement_id": job.agreement_id,
                        "build_id": build_id,
                        "source_checksum": checksum,
                        "chunker_version": STRUCTURE_AWARE_CHUNKER_VERSION,
                        "ordinal": chunk.ordinal,
                        "heading_path": list(chunk.heading_path),
                        "anchor_ids": list(chunk.anchor_ids),
                        "content": chunk.text,
                    }
                    for chunk in chunks
                ],
            )
            stale_ids = (
                connection.execute(
                    select(retrieval_index_builds.c.id).where(
                        retrieval_index_builds.c.organization_id == job.organization_id,
                        retrieval_index_builds.c.workspace_id == job.workspace_id,
                        retrieval_index_builds.c.agreement_id == job.agreement_id,
                        retrieval_index_builds.c.state == "active",
                        retrieval_index_builds.c.id != build_id,
                    )
                )
                .scalars()
                .all()
            )
            if stale_ids:
                connection.execute(
                    update(retrieval_index_builds)
                    .where(retrieval_index_builds.c.id.in_(stale_ids))
                    .values(state="stale")
                )
            connection.execute(
                update(retrieval_index_builds)
                .where(retrieval_index_builds.c.id == build_id)
                .values(state="active", activated_at=now)
            )
            if stale_ids:
                connection.execute(
                    delete(retrieval_chunks).where(retrieval_chunks.c.build_id.in_(stale_ids))
                )


def structural_chunks_from_manifest(manifest: Mapping[str, object]) -> tuple[RetrievalChunk, ...]:
    checksum = _source_checksum(manifest)
    current_heading_path: tuple[str, ...] = ()
    groups: list[tuple[tuple[str, ...], list[tuple[str, str]]]] = []
    for block in _blocks(manifest):
        kind = block.get("kind")
        text = _required_string(block, "text").strip()
        if not text:
            continue
        if kind == "heading":
            current_heading_path = (*current_heading_path, text)
            groups.append((current_heading_path, [(_required_string(block, "anchor_id"), text)]))
        elif groups:
            groups[-1][1].append((_required_string(block, "anchor_id"), text))
        else:
            groups.append((current_heading_path, [(_required_string(block, "anchor_id"), text)]))
    chunks: list[RetrievalChunk] = []
    for heading_path, entries in groups:
        chunks.extend(_chunks_for_group(checksum, heading_path, entries, len(chunks)))
    return tuple(chunks)


def _chunks_for_group(
    checksum: str,
    heading_path: tuple[str, ...],
    entries: list[tuple[str, str]],
    starting_ordinal: int,
) -> list[RetrievalChunk]:
    group_text = "\n".join(entry_text for _, entry_text in entries)
    if _token_count(group_text) <= MAX_CHUNK_TOKENS:
        anchor_ids = tuple(anchor for anchor, _ in entries)
        return [
            RetrievalChunk(
                chunk_id=_chunk_id(checksum, anchor_ids, 0),
                ordinal=starting_ordinal,
                heading_path=heading_path,
                anchor_ids=anchor_ids,
                text=group_text,
            )
        ]

    source_tokens = [
        (anchor_id, token) for anchor_id, entry_text in entries for token in entry_text.split()
    ]
    chunks: list[RetrievalChunk] = []
    current_tokens: list[tuple[str, str]] = []
    start_token = 0
    for source_anchor, token in source_tokens:
        if current_tokens and len(current_tokens) == MAX_CHUNK_TOKENS:
            chunks.append(
                _chunk_from_tokens(
                    checksum,
                    heading_path,
                    current_tokens,
                    starting_ordinal + len(chunks),
                    start_token,
                )
            )
            overlap = current_tokens[-CHUNK_OVERLAP_TOKENS:]
            start_token += MAX_CHUNK_TOKENS - len(overlap)
            current_tokens = [*overlap, (source_anchor, token)]
        else:
            current_tokens.append((source_anchor, token))
    if current_tokens:
        chunks.append(
            _chunk_from_tokens(
                checksum,
                heading_path,
                current_tokens,
                starting_ordinal + len(chunks),
                start_token,
            )
        )
    return chunks


def _chunk_from_tokens(
    checksum: str,
    heading_path: tuple[str, ...],
    tokens: list[tuple[str, str]],
    ordinal: int,
    start_token: int,
) -> RetrievalChunk:
    anchor_ids = tuple(dict.fromkeys(anchor_id for anchor_id, _ in tokens))
    return RetrievalChunk(
        chunk_id=_chunk_id(checksum, anchor_ids, start_token),
        ordinal=ordinal,
        heading_path=heading_path,
        anchor_ids=anchor_ids,
        text=" ".join(token for _, token in tokens),
    )


def _manifest_from_artifact(storage: ArtifactStorage, key: str) -> Mapping[str, object]:
    raw = storage.read(key)
    if raw is None:
        raise ValueError("Canonical analysis artifact is unavailable")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("Canonical analysis artifact must be an object")
    return cast(Mapping[str, object], decoded)


def _source_checksum(manifest: Mapping[str, object]) -> str:
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("Canonical analysis artifact has no source")
    return _required_string(source, "checksum")


def _blocks(manifest: Mapping[str, object]) -> list[Mapping[str, object]]:
    document = manifest.get("document")
    if not isinstance(document, Mapping) or not isinstance(document.get("pages"), list):
        raise ValueError("Canonical analysis artifact has no document pages")
    blocks: list[Mapping[str, object]] = []
    for page in cast(list[object], document["pages"]):
        if not isinstance(page, Mapping) or not isinstance(page.get("blocks"), list):
            raise ValueError("Canonical analysis artifact has malformed page blocks")
        blocks.extend(cast(list[Mapping[str, object]], page["blocks"]))
    return blocks


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Canonical analysis artifact has invalid {key}")
    return result


def _token_count(value: str) -> int:
    return len(value.split())


def _chunk_id(checksum: str, anchor_ids: tuple[str, ...], start_token: int) -> str:
    payload = json.dumps(
        {
            "anchor_ids": anchor_ids,
            "chunker_version": STRUCTURE_AWARE_CHUNKER_VERSION,
            "source_checksum": checksum,
            "start_token": start_token,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"chunk-{sha256(payload.encode()).hexdigest()[:32]}"
