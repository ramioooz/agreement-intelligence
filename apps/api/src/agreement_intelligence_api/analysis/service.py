from __future__ import annotations

import json
from typing import Any, Protocol, cast


class ArtifactStorage(Protocol):
    def read(self, key: str) -> Any | None: ...


def load_analysis(storage: ArtifactStorage, artifact_key: str | None) -> dict[str, object] | None:
    if artifact_key is None:
        return None
    document = storage.read(artifact_key)
    if document is None:
        return None
    return cast(dict[str, object], json.loads(document.content))
