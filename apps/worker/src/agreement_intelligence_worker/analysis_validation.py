from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NotRequired, TypedDict

from agreement_intelligence_worker.analysis_provider import ProviderAnalysis

MAX_STRING_LENGTH = 4_000
MAX_CLAUSES = 100
MAX_RISKS = 100
MAX_SUMMARIES = 2
MAX_NORMALIZED_FIELDS = 25
MAX_CITATION_ANCHORS = 20

CLAUSE_CATEGORIES = frozenset(
    {
        "termination",
        "confidentiality",
        "governing_law",
        "liability",
        "dispute_resolution",
        "other_needs_review",
    }
)
RISK_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
SUMMARY_TYPES = frozenset({"business", "legal"})
AGREEMENT_FAMILIES = frozenset(
    {
        "client_agreement",
        "liquidity_provider_agreement",
        "non_agreement_material",
        "unknown_needs_review",
    }
)


class ProviderOutputValidationError(ValueError):
    """Raised when provider output is unsafe to persist as an analysis artifact."""


class Classification(TypedDict):
    family: str
    confidence: float
    rationale: str
    citation_anchor_ids: list[str]


class NormalizedField(TypedDict):
    name: str
    value: str


class Clause(TypedDict):
    category: str
    normalized_fields: list[NormalizedField]
    source_excerpt: str
    confidence: float
    citation_anchor_ids: list[str]


class Risk(TypedDict):
    severity: str
    explanation: str
    affected_category: str
    confidence: float
    citation_anchor_ids: list[str]


class Summary(TypedDict):
    claim: str
    citation_anchor_ids: list[str]


class Provenance(TypedDict):
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    provider: NotRequired[str]
    endpoint_kind: NotRequired[str]
    configuration_version: NotRequired[str]
    total_tokens: NotRequired[int | None]
    cost_usd: NotRequired[float | None]
    retry_outcome: NotRequired[str]
    fallback_outcome: NotRequired[str]
    safe_failure_reason: NotRequired[str | None]


@dataclass(frozen=True)
class ValidatedAnalysis:
    classification: Classification
    clauses: list[Clause]
    risks: list[Risk]
    summaries: dict[str, Summary]
    provenance: Provenance


def validate_provider_analysis(
    analysis: ProviderAnalysis, allowed_anchor_ids: Mapping[str, str] | set[str]
) -> ValidatedAnalysis:
    """Validate and bound provider output before it becomes an artifact."""
    allowed_anchors = _allowed_anchors(allowed_anchor_ids)
    classification = _classification(analysis.classification, allowed_anchors)
    clauses: list[Clause] = _claims(
        analysis.clauses, MAX_CLAUSES, _clause, allowed_anchors, "clauses"
    )
    risks: list[Risk] = _claims(analysis.risks, MAX_RISKS, _risk, allowed_anchors, "risks")
    summaries = _summaries(analysis.summaries, allowed_anchors)
    provenance = _provenance(analysis)
    return ValidatedAnalysis(classification, clauses, risks, summaries, provenance)


def _allowed_anchors(anchors: Mapping[str, str] | set[str]) -> dict[str, str]:
    if len(anchors) > MAX_CITATION_ANCHORS * MAX_CLAUSES:
        raise ProviderOutputValidationError("Too many allowed citation anchors")
    if isinstance(anchors, Mapping):
        return {
            _string(anchor, "citation anchor"): _string(text, "requested evidence")
            for anchor, text in anchors.items()
        }
    return {_string(anchor, "citation anchor"): "" for anchor in anchors}


def _classification(value: object, allowed_anchors: dict[str, str]) -> Classification:
    payload = _mapping(value, "classification")
    _required_keys(payload, {"family", "confidence", "rationale", "citation_anchor_ids"})
    rationale = _string(payload["rationale"], "classification rationale")
    family = _string(payload["family"], "classification family")
    if family not in AGREEMENT_FAMILIES:
        raise ProviderOutputValidationError("Unsupported agreement family")
    claim: Classification = {
        "family": family,
        "confidence": _confidence(payload["confidence"]),
        "rationale": rationale,
        "citation_anchor_ids": _citations(payload["citation_anchor_ids"], allowed_anchors),
    }
    if any((claim["family"], rationale)):
        _require_evidence(claim["citation_anchor_ids"])
    return claim


def _clause(value: object, allowed_anchors: dict[str, str]) -> Clause:
    payload = _mapping(value, "clause")
    _required_keys(
        payload,
        {"category", "normalized_fields", "source_excerpt", "confidence", "citation_anchor_ids"},
    )
    category = _string(payload["category"], "clause category")
    if category not in CLAUSE_CATEGORIES:
        raise ProviderOutputValidationError("Unsupported clause category")
    fields_value = _list(payload["normalized_fields"], "normalized fields")
    _bounded_collection(fields_value, MAX_NORMALIZED_FIELDS, "normalized fields")
    claim: Clause = {
        "category": category,
        "normalized_fields": [_normalized_field(item) for item in fields_value],
        "source_excerpt": _string(payload["source_excerpt"], "source excerpt"),
        "confidence": _confidence(payload["confidence"]),
        "citation_anchor_ids": _citations(payload["citation_anchor_ids"], allowed_anchors),
    }
    _require_evidence(claim["citation_anchor_ids"])
    if not any(
        _excerpt_is_in_requested_evidence(claim["source_excerpt"], allowed_anchors[anchor_id])
        for anchor_id in claim["citation_anchor_ids"]
    ):
        raise ProviderOutputValidationError(
            "Provider source excerpt is not supported by cited evidence"
        )
    return claim


def _risk(value: object, allowed_anchors: dict[str, str]) -> Risk:
    payload = _mapping(value, "risk")
    _required_keys(
        payload,
        {"severity", "explanation", "affected_category", "confidence", "citation_anchor_ids"},
    )
    severity = _string(payload["severity"], "risk severity")
    category = _string(payload["affected_category"], "risk affected category")
    if severity not in RISK_SEVERITIES:
        raise ProviderOutputValidationError("Unsupported risk severity")
    if category not in CLAUSE_CATEGORIES:
        raise ProviderOutputValidationError("Unsupported risk category")
    claim: Risk = {
        "severity": severity,
        "explanation": _string(payload["explanation"], "risk explanation"),
        "affected_category": category,
        "confidence": _confidence(payload["confidence"]),
        "citation_anchor_ids": _citations(payload["citation_anchor_ids"], allowed_anchors),
    }
    _require_evidence(claim["citation_anchor_ids"])
    return claim


def _summaries(value: object, allowed_anchors: dict[str, str]) -> dict[str, Summary]:
    payload = _mapping(value, "summaries")
    if set(payload) != SUMMARY_TYPES:
        raise ProviderOutputValidationError("Provider response is missing required summaries")
    summaries: dict[str, Summary] = {}
    for summary_type, summary in payload.items():
        if summary_type not in SUMMARY_TYPES:
            raise ProviderOutputValidationError("Unsupported summary type")
        claim = _mapping(summary, "summary")
        _required_keys(claim, {"claim", "citation_anchor_ids"})
        result: Summary = {
            "claim": _string(claim["claim"], "summary claim"),
            "citation_anchor_ids": _citations(claim["citation_anchor_ids"], allowed_anchors),
        }
        if result["claim"]:
            _require_evidence(result["citation_anchor_ids"])
        summaries[summary_type] = result
    return summaries


def _provenance(analysis: ProviderAnalysis) -> Provenance:
    model = _string(analysis.model, "model")
    input_tokens = _optional_nonnegative_integer(analysis.input_tokens, "input tokens")
    output_tokens = _optional_nonnegative_integer(analysis.output_tokens, "output tokens")
    latency_ms = _nonnegative_integer(analysis.latency_ms, "latency")
    provenance: Provenance = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
    }
    gateway = analysis.gateway_provenance
    if gateway is None:
        return provenance
    provenance.update(
        {
            "model": gateway.model,
            "input_tokens": gateway.input_tokens,
            "output_tokens": gateway.output_tokens,
            "latency_ms": gateway.latency_ms,
            "provider": gateway.provider,
            "endpoint_kind": gateway.endpoint_kind,
            "configuration_version": gateway.configuration_version,
            "total_tokens": gateway.total_tokens,
            "cost_usd": gateway.cost_usd,
            "retry_outcome": gateway.retry_outcome,
            "fallback_outcome": gateway.fallback_outcome,
            "safe_failure_reason": gateway.safe_failure_reason,
        }
    )
    return provenance


def _claims[Claim](
    values: object,
    limit: int,
    validator: Callable[[object, dict[str, str]], Claim],
    allowed_anchors: dict[str, str],
    name: str,
) -> list[Claim]:
    items = _list(values, name)
    _bounded_collection(items, limit, name)
    return [validator(item, allowed_anchors) for item in items]


def _normalized_field(value: object) -> NormalizedField:
    payload = _mapping(value, "normalized field")
    _required_keys(payload, {"name", "value"})
    return {
        "name": _string(payload["name"], "normalized field name"),
        "value": _string(payload["value"], "normalized field value"),
    }


def _citations(value: object, allowed_anchors: dict[str, str]) -> list[str]:
    citations = _list(value, "citation anchors")
    _bounded_collection(citations, MAX_CITATION_ANCHORS, "citation anchors")
    anchor_ids = [_string(anchor, "citation anchor") for anchor in citations]
    if not set(anchor_ids).issubset(allowed_anchors):
        raise ProviderOutputValidationError("Provider referenced an unknown citation anchor")
    return anchor_ids


def _excerpt_is_in_requested_evidence(excerpt: str, evidence: str) -> bool:
    return not evidence or _normalized_evidence_text(excerpt) in _normalized_evidence_text(evidence)


def _normalized_evidence_text(value: str) -> str:
    return " ".join(value.casefold().replace("’", "'").replace("‘", "'").split())


def _require_evidence(citation_anchor_ids: list[str]) -> None:
    if not citation_anchor_ids:
        raise ProviderOutputValidationError("All claims require evidence")


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderOutputValidationError("Confidence must be a number")
    confidence = float(value)
    if not 0.0 <= confidence <= 1.0:
        raise ProviderOutputValidationError("Confidence must be between zero and one")
    return confidence


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProviderOutputValidationError(f"Invalid {name} structure")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ProviderOutputValidationError(f"Invalid {name} structure")
    return value


def _required_keys(payload: dict[str, object], keys: set[str]) -> None:
    if set(payload) != keys:
        raise ProviderOutputValidationError("Provider response contains invalid fields")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ProviderOutputValidationError(f"Invalid {name}")
    if len(value) > MAX_STRING_LENGTH:
        raise ProviderOutputValidationError(f"{name} exceeds maximum length")
    return value


def _bounded_collection(values: list[object], limit: int, name: str) -> None:
    if len(values) > limit:
        raise ProviderOutputValidationError(f"Too many {name}")


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderOutputValidationError(f"Invalid {name}")
    return value


def _optional_nonnegative_integer(value: object, name: str) -> int | None:
    return None if value is None else _nonnegative_integer(value, name)
