from __future__ import annotations

import json
from typing import Any

from _pytest.monkeypatch import MonkeyPatch
from agreement_intelligence_worker.analysis_provider import (
    HostedAnalysisProvider,
    provider_from_environment,
)

VALID_RESPONSE = json.dumps(
    {
        "classification": {"family": "unknown_needs_review"},
        "clauses": [],
        "risks": [],
        "summaries": {},
    }
)


class RecordingClient:
    def __init__(self, response: str) -> None:
        self.response = _Response(response)
        self.responses = self
        self.requested_anchor_ids: list[str] = []
        self.requested_text = ""

    def create(self, **kwargs: Any) -> _Response:
        input_item = kwargs["input"][0]
        self.requested_text = input_item["content"][0]["text"]
        self.requested_anchor_ids = [
            block["anchor_id"] for block in json.loads(self.requested_text)["blocks"]
        ]
        return self.response


class _Response:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text
        self.usage = None


def test_provider_is_disabled_without_an_api_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert provider_from_environment() is None


def test_provider_receives_only_anchor_ids_and_extracted_blocks() -> None:
    client = RecordingClient(response=VALID_RESPONSE)
    provider = HostedAnalysisProvider(client=client, model="gpt-5.4-mini")

    provider.analyze([("citation-a", "Termination is permitted on notice.")])

    assert client.requested_anchor_ids == ["citation-a"]
    assert "Termination is permitted" in client.requested_text
