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
        "classification": {
            "family": "unknown_needs_review",
            "confidence": 0.0,
            "rationale": "Insufficient agreement-family evidence.",
            "citation_anchor_ids": ["citation-a"],
        },
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
        self.requested_format: dict[str, object] = {}

    def create(self, **kwargs: Any) -> _Response:
        input_item = kwargs["input"][0]
        self.requested_text = input_item["content"][0]["text"]
        self.requested_anchor_ids = [
            block["anchor_id"] for block in json.loads(self.requested_text)["blocks"]
        ]
        self.requested_format = kwargs["text"]["format"]
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


def test_provider_requests_a_closed_strict_json_schema() -> None:
    client = RecordingClient(response=VALID_RESPONSE)
    provider = HostedAnalysisProvider(client=client, model="gpt-5.4-mini")

    provider.analyze([("citation-a", "Termination is permitted on notice.")])

    response_format = client.requested_format
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    _assert_object_schemas_are_closed(response_format["schema"])


def _assert_object_schemas_are_closed(schema: object) -> None:
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False
    for value in schema.values():
        if isinstance(value, dict):
            _assert_object_schemas_are_closed(value)
        elif isinstance(value, list):
            for item in value:
                _assert_object_schemas_are_closed(item)
