from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import cast

import pytest
from agreement_intelligence_worker.risk_explanation import (
    RiskExplanationRequest,
    explain_risk,
)


@pytest.mark.parametrize(
    ("result", "confidence", "citation_ids", "source_text", "review_status"),
    [
        ("satisfied", 0.94, ["citation-liability"], "Liability is capped.", "complete"),
        (
            "non_compliant",
            0.91,
            ["citation-liability"],
            "The supplier accepts unlimited liability.",
            "review_required",
        ),
        (
            "needs_review",
            0.61,
            ["citation-liability"],
            "Liability terms are unclear.",
            "review_required",
        ),
        ("missing", 0.0, [], None, "review_required"),
    ],
)
def test_explain_risk_calibrates_each_deterministic_outcome(
    result: str,
    confidence: float,
    citation_ids: list[str],
    source_text: str | None,
    review_status: str,
) -> None:
    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result=result,
            confidence=confidence,
            citation_ids=citation_ids,
            cited_clause_text=source_text,
        )
    )

    assert payload.version == "playbook-risk.v1"
    assert payload.severity == "critical"
    assert payload.risk_rationale == "Unlimited liability exceeds the approved risk position."
    assert payload.risk_confidence == confidence
    assert payload.review_status == review_status
    assert payload.citation_ids == citation_ids
    assert payload.model_explanation is None


def test_explain_risk_accepts_a_grounded_model_explanation_without_changing_severity() -> None:
    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result="non_compliant",
            confidence=0.91,
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
        ),
        model_explainer=lambda _: {
            "rationale": "The cited clause accepts unlimited liability.",
            "citation_ids": ["citation-liability"],
        },
    )

    assert payload.severity == "critical"
    assert payload.model_explanation == "The cited clause accepts unlimited liability."


def test_explain_risk_rejects_ungrounded_citations() -> None:
    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result="non_compliant",
            confidence=0.91,
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
        ),
        model_explainer=lambda _: {
            "rationale": "This is harmless.",
            "citation_ids": ["citation-not-in-evidence"],
        },
    )

    assert payload.model_explanation is None


def test_explain_risk_rejects_extra_model_fields_without_changing_severity() -> None:
    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result="non_compliant",
            confidence=0.91,
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
        ),
        model_explainer=lambda _: {
            "rationale": "This is harmless.",
            "citation_ids": ["citation-liability"],
            "severity": "low",
        },
    )

    assert payload.severity == "critical"
    assert payload.risk_rationale == "Unlimited liability exceeds the approved risk position."
    assert payload.model_explanation is None


def test_explain_risk_falls_back_when_the_model_returns_a_malformed_response() -> None:
    def malformed(_: RiskExplanationRequest) -> Mapping[str, object]:
        return cast(Mapping[str, object], ["rationale", "citation_ids"])

    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result="non_compliant",
            confidence=0.91,
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
        ),
        model_explainer=malformed,
    )

    assert payload.model_explanation is None


def test_explain_risk_falls_back_when_malformed_mapping_validation_raises() -> None:
    class BrokenMapping(Mapping[str, object]):
        def __iter__(self) -> Iterator[str]:
            return iter(("rationale", "citation_ids"))

        def __len__(self) -> int:
            return 2

        def __getitem__(self, _: str) -> object:
            raise RuntimeError("malformed model response")

    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result="non_compliant",
            confidence=0.91,
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
        ),
        model_explainer=lambda _: BrokenMapping(),
    )

    assert payload.model_explanation is None


def test_explain_risk_falls_back_when_the_model_raises() -> None:
    def failing(_: RiskExplanationRequest) -> Mapping[str, object]:
        raise RuntimeError("model unavailable")

    payload = explain_risk(
        RiskExplanationRequest(
            rule_severity="critical",
            rule_rationale="Unlimited liability exceeds the approved risk position.",
            deterministic_result="non_compliant",
            confidence=0.91,
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
        ),
        model_explainer=failing,
    )

    assert payload.model_explanation is None
