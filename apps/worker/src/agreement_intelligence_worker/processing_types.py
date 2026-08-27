"""Dependency-light processing value objects shared by processors and commit fences."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CompletedArtifact:
    job_id: UUID
    key: str
