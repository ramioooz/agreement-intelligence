"""Immutable object operation used inside caller-owned database commit fences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agreement_intelligence_worker.processing_types import CompletedArtifact


class ImmutableArtifactStorage(Protocol):
    def put_immutable(self, key: str, content: bytes, *, content_type: str) -> bool: ...

    def read(self, key: str) -> bytes | None: ...


@dataclass(frozen=True)
class PreparedArtifact:
    artifact: CompletedArtifact
    content: bytes | None
    content_type: str | None


def write_or_read_canonical(
    storage: ImmutableArtifactStorage,
    prepared: PreparedArtifact,
) -> bytes:
    """Conditionally create an immutable object or return its first valid candidate."""
    if prepared.content is None or prepared.content_type is None:
        raise ValueError("object-backed artifact content is required")
    if storage.put_immutable(
        prepared.artifact.key,
        prepared.content,
        content_type=prepared.content_type,
    ):
        return prepared.content
    canonical = storage.read(prepared.artifact.key)
    if canonical is None:
        raise RuntimeError("immutable artifact disappeared after create conflict")
    return canonical
