from __future__ import annotations

import json
from importlib import import_module
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
        self.requested_instruction = ""
        self.requested_format: dict[str, object] = {}

    def create(self, **kwargs: Any) -> _Response:
        for input_item in kwargs["input"]:
            text = input_item["content"][0]["text"]
            if input_item["role"] == "system":
                self.requested_instruction = text
            if input_item["role"] == "user":
                self.requested_text = text
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


def test_provider_sends_bounded_instruction_for_cited_agreement_analysis() -> None:
    client = RecordingClient(response=VALID_RESPONSE)
    provider = HostedAnalysisProvider(client=client, model="gpt-5.4-mini")

    provider.analyze([("citation-a", "Termination is permitted on notice.")])

    assert len(client.requested_instruction) <= 1_000
    assert "classification" in client.requested_instruction
    assert "clauses" in client.requested_instruction
    assert "risks" in client.requested_instruction
    assert "summaries" in client.requested_instruction
    assert "only cite supplied anchor IDs" in client.requested_instruction


def test_fallback_comparator_only_requests_a_cited_comparison_of_approved_language() -> None:
    provider_module = import_module("agreement_intelligence_worker.analysis_provider")
    comparator_type = getattr(provider_module, "HostedFallbackComparator", None)
    assert comparator_type is not None, "fallback comparator provider is missing"
    request_module = import_module("agreement_intelligence_worker.fallback_suggestions")
    client = _ComparisonRecordingClient(
        json.dumps(
            {
                "comparison_kind": "clause_differs_from_approved_position",
                "citation_ids": ["citation-liability"],
            }
        )
    )

    response = comparator_type(client=client, model="gpt-5.4-mini")(
        request_module.FallbackSuggestionRequest(
            rule_id="rule-liability",
            playbook_version_id="version-4",
            finding_result="non_compliant",
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
            preferred_language="Liability is capped at fees paid.",
            fallback_language="Liability is capped at USD 100,000.",
        )
    )

    assert response == {
        "comparison_kind": "clause_differs_from_approved_position",
        "citation_ids": ["citation-liability"],
    }
    assert (
        "do not draft, rewrite, or propose policy language" in client.requested_instruction.lower()
    )
    assert json.loads(client.requested_text) == {
        "citation_ids": ["citation-liability"],
        "cited_clause_text": "The supplier accepts unlimited liability.",
        "approved_language": "Liability is capped at USD 100,000.",
    }


class _ComparisonRecordingClient:
    def __init__(self, response: str) -> None:
        self.response = _Response(response)
        self.responses = self
        self.requested_text = ""
        self.requested_instruction = ""

    def create(self, **kwargs: Any) -> _Response:
        for input_item in kwargs["input"]:
            text = input_item["content"][0]["text"]
            if input_item["role"] == "system":
                self.requested_instruction = text
            if input_item["role"] == "user":
                self.requested_text = text
        return self.response


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
