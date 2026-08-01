from __future__ import annotations

import pytest
from agreement_intelligence_worker.analysis_provider import ProviderAnalysis
from agreement_intelligence_worker.analysis_validation import (
    ProviderOutputValidationError,
    validate_provider_analysis,
)

VALID_RESPONSE = ProviderAnalysis(
    classification={
        "family": "client_agreement",
        "confidence": 0.91,
        "rationale": "The agreement governs a client account.",
        "citation_anchor_ids": ["citation-a"],
    },
    clauses=[
        {
            "category": "termination",
            "normalized_fields": [{"name": "notice", "value": "30 days"}],
            "source_excerpt": "Either party may terminate with 30 days' notice.",
            "confidence": 0.88,
            "citation_anchor_ids": ["citation-a"],
        }
    ],
    risks=[
        {
            "severity": "high",
            "explanation": "Termination is available without cause.",
            "affected_category": "termination",
            "confidence": 0.82,
            "citation_anchor_ids": ["citation-a"],
        }
    ],
    summaries={
        "business": {
            "claim": "The client account may be terminated on 30 days' notice.",
            "citation_anchor_ids": ["citation-a"],
        },
        "legal": {
            "claim": "The termination clause applies to either party.",
            "citation_anchor_ids": ["citation-a"],
        },
    },
    model="test-model",
    input_tokens=10,
    output_tokens=20,
    latency_ms=30,
)


def test_validator_accepts_cited_clause_risk_and_summary() -> None:
    validated = validate_provider_analysis(VALID_RESPONSE, {"citation-a"})

    assert validated.risks[0]["citation_anchor_ids"] == ["citation-a"]


def test_validator_rejects_a_claim_with_an_unknown_anchor() -> None:
    unknown_anchor_response = ProviderAnalysis(
        **{
            **VALID_RESPONSE.__dict__,
            "risks": [{**VALID_RESPONSE.risks[0], "citation_anchor_ids": ["citation-z"]}],
        }
    )

    with pytest.raises(ProviderOutputValidationError, match="unknown citation anchor"):
        validate_provider_analysis(unknown_anchor_response, {"citation-a"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("citation_anchor_ids", [], "All claims require evidence"),
        ("confidence", 1.01, "Confidence must be between zero and one"),
    ],
)
def test_validator_rejects_invalid_risk_claims(field: str, value: object, message: str) -> None:
    response = ProviderAnalysis(
        **{
            **VALID_RESPONSE.__dict__,
            "risks": [{**VALID_RESPONSE.risks[0], field: value}],
        }
    )

    with pytest.raises(ProviderOutputValidationError, match=message):
        validate_provider_analysis(response, {"citation-a"})


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("clauses", "category", "unbounded_category"),
        ("risks", "severity", "urgent"),
        ("risks", "affected_category", "unbounded_category"),
    ],
)
def test_validator_rejects_unknown_category_or_severity(
    section: str, field: str, value: str
) -> None:
    response = ProviderAnalysis(
        **{
            **VALID_RESPONSE.__dict__,
            section: [{**getattr(VALID_RESPONSE, section)[0], field: value}],
        }
    )

    with pytest.raises(ProviderOutputValidationError):
        validate_provider_analysis(response, {"citation-a"})


def test_validator_rejects_oversized_content_before_artifact_creation() -> None:
    response = ProviderAnalysis(
        **{
            **VALID_RESPONSE.__dict__,
            "summaries": {
                "business": {
                    "claim": "x" * 4_001,
                    "citation_anchor_ids": ["citation-a"],
                },
                "legal": VALID_RESPONSE.summaries["legal"],
            },
        }
    )

    with pytest.raises(ProviderOutputValidationError, match="maximum length"):
        validate_provider_analysis(response, {"citation-a"})


def test_validator_rejects_an_unknown_agreement_family() -> None:
    response = ProviderAnalysis(
        **{
            **VALID_RESPONSE.__dict__,
            "classification": {**VALID_RESPONSE.classification, "family": "unsupported"},
        }
    )

    with pytest.raises(ProviderOutputValidationError, match="Unsupported agreement family"):
        validate_provider_analysis(response, {"citation-a"})


@pytest.mark.parametrize("summaries", [{}, {"business": VALID_RESPONSE.summaries["business"]}])
def test_validator_rejects_omitted_or_empty_required_summaries(
    summaries: dict[str, dict[str, object]],
) -> None:
    response = ProviderAnalysis(**{**VALID_RESPONSE.__dict__, "summaries": summaries})

    with pytest.raises(ProviderOutputValidationError, match="required summaries"):
        validate_provider_analysis(response, {"citation-a"})
