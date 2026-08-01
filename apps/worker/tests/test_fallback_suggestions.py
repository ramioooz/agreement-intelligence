from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec


def test_suggest_fallback_selects_the_approved_fallback_with_a_cited_ai_comparison() -> None:
    module_name = "agreement_intelligence_worker.fallback_suggestions"
    assert find_spec(module_name) is not None, "fallback suggestion producer is missing"
    suggestions = import_module(module_name)

    suggestion = suggestions.suggest_fallback(
        suggestions.FallbackSuggestionRequest(
            rule_id="rule-liability",
            playbook_version_id="version-4",
            finding_result="non_compliant",
            citation_ids=["citation-liability"],
            cited_clause_text="The supplier accepts unlimited liability.",
            preferred_language="Liability is capped at fees paid in the prior 12 months.",
            fallback_language="Liability is capped at USD 100,000.",
        ),
        model_comparator=lambda _: {
            "comparison_kind": "clause_differs_from_approved_position",
            "citation_ids": ["citation-liability"],
        },
    )

    assert suggestion is not None
    assert suggestion.version == "playbook-fallback-suggestion.v1"
    assert suggestion.rule_id == "rule-liability"
    assert suggestion.playbook_version_id == "version-4"
    assert suggestion.suggested_language == "Liability is capped at USD 100,000."
    assert suggestion.citation_ids == ["citation-liability"]
    assert suggestion.comparison_kind == "clause_differs_from_approved_position"
    assert suggestion.comparison == "The cited clause differs from the approved position."
    assert suggestion.ai_generated is True


def test_suggest_fallback_emits_only_a_review_recommendation_without_approved_language() -> None:
    suggestions = import_module("agreement_intelligence_worker.fallback_suggestions")

    suggestion = suggestions.suggest_fallback(
        suggestions.FallbackSuggestionRequest(
            rule_id="rule-liability",
            playbook_version_id="version-4",
            finding_result="missing",
            citation_ids=[],
            cited_clause_text=None,
            preferred_language=None,
            fallback_language=None,
        )
    )

    assert suggestion is not None
    assert suggestion.rule_id == "rule-liability"
    assert suggestion.playbook_version_id == "version-4"
    assert suggestion.suggested_language is None
    assert suggestion.review_recommendation == (
        "No approved language is available; reviewer assessment is required."
    )
    assert suggestion.citation_ids == []
    assert suggestion.comparison_kind is None
    assert suggestion.comparison is None
    assert suggestion.ai_generated is False
