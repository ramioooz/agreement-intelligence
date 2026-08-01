from __future__ import annotations

import json
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, cast

from openai import APIConnectionError, APIError, APIStatusError, OpenAI, OpenAIError

MAX_BLOCKS = 100
MAX_CHARACTERS_PER_BLOCK = 4_000
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})
_ANALYSIS_INSTRUCTION = (
    "Analyze only the supplied agreement blocks. Return classification using families "
    "client_agreement, "
    "liquidity_provider_agreement, non_agreement_material, or unknown_needs_review; use "
    "non_agreement_material only when the material is confidently not an agreement, and "
    "unknown_needs_review only when its agreement status or family is uncertain; "
    "clause categories termination, "
    "confidentiality, governing_law, liability, dispute_resolution, or other_needs_review; "
    "and risk severities low, medium, high, or critical. Return clauses, risks, and business "
    "and legal summaries. "
    "Ground every substantive claim in supplied anchor IDs and only cite supplied anchor IDs. "
    "Do not invent facts."
)


@dataclass(frozen=True)
class ProviderAnalysis:
    classification: dict[str, object]
    clauses: list[dict[str, object]]
    risks: list[dict[str, object]]
    summaries: dict[str, dict[str, object]]
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class AnalysisProvider(Protocol):
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis: ...


class ProviderTransientError(Exception):
    """The provider could not be reached safely and processing should retry."""


class ProviderPermanentError(Exception):
    """The provider rejected the request and deterministic output remains usable."""


class HostedAnalysisProvider:
    def __init__(self, *, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        started_at = perf_counter()
        try:
            response = self._client.responses.create(
                model=self._model,
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": _ANALYSIS_INSTRUCTION}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps({"blocks": _bounded_blocks(blocks)}),
                            }
                        ],
                    },
                ],
                text={"format": _response_format()},
            )
        except APIStatusError as error:
            if error.status_code in _RETRYABLE_STATUS_CODES or error.status_code >= 500:
                raise ProviderTransientError("Provider returned a retryable response") from error
            raise ProviderPermanentError("Provider rejected the analysis request") from error
        except (APIConnectionError, APIError) as error:
            raise ProviderTransientError("Provider connection was unavailable") from error
        except OpenAIError as error:
            raise ProviderPermanentError("Provider rejected the analysis request") from error
        parsed = cast(object, json.loads(response.output_text))
        payload = _analysis_payload(parsed)
        usage = getattr(response, "usage", None)
        return ProviderAnalysis(
            classification=payload["classification"],
            clauses=payload["clauses"],
            risks=payload["risks"],
            summaries=payload["summaries"],
            model=self._model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=round((perf_counter() - started_at) * 1_000),
        )


def provider_from_environment() -> AnalysisProvider | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return HostedAnalysisProvider(
        client=OpenAI(api_key=api_key),
        model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
    )


def _bounded_blocks(blocks: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"anchor_id": anchor_id, "text": text[:MAX_CHARACTERS_PER_BLOCK]}
        for anchor_id, text in blocks[:MAX_BLOCKS]
    ]


def _response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "agreement_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["classification", "clauses", "risks", "summaries"],
            "properties": {
                "classification": _object_schema(
                    {
                        "family": {"type": "string"},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                        "citation_anchor_ids": _string_array_schema(),
                    }
                ),
                "clauses": {
                    "type": "array",
                    "items": _object_schema(
                        {
                            "category": {"type": "string"},
                            "normalized_fields": {
                                "type": "array",
                                "items": _object_schema(
                                    {"name": {"type": "string"}, "value": {"type": "string"}}
                                ),
                            },
                            "source_excerpt": {"type": "string"},
                            "confidence": {"type": "number"},
                            "citation_anchor_ids": _string_array_schema(),
                        }
                    ),
                },
                "risks": {
                    "type": "array",
                    "items": _object_schema(
                        {
                            "severity": {"type": "string"},
                            "explanation": {"type": "string"},
                            "affected_category": {"type": "string"},
                            "confidence": {"type": "number"},
                            "citation_anchor_ids": _string_array_schema(),
                        }
                    ),
                },
                "summaries": _object_schema(
                    {
                        "business": _summary_schema(),
                        "legal": _summary_schema(),
                    }
                ),
            },
        },
    }


def _object_schema(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _string_array_schema() -> dict[str, object]:
    return {"type": "array", "items": {"type": "string"}}


def _summary_schema() -> dict[str, object]:
    return _object_schema(
        {
            "claim": {"type": "string"},
            "citation_anchor_ids": _string_array_schema(),
        }
    )


def _analysis_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Provider response must be a JSON object")
    classification = payload.get("classification")
    clauses = payload.get("clauses")
    risks = payload.get("risks")
    summaries = payload.get("summaries")
    if (
        not isinstance(classification, dict)
        or not _is_list_of_dicts(clauses)
        or not _is_list_of_dicts(risks)
        or not _is_dict_of_dicts(summaries)
    ):
        raise ValueError("Provider response has an invalid analysis shape")
    return {
        "classification": classification,
        "clauses": clauses,
        "risks": risks,
        "summaries": summaries,
    }


def _is_list_of_dicts(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _is_dict_of_dicts(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, dict) for key, item in value.items()
    )
