from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agreement_intelligence_worker.risk_explanation import grounded_model_text

FALLBACK_SUGGESTION_PAYLOAD_VERSION = "playbook-fallback-suggestion.v1"
_SUGGESTIBLE_RESULTS = frozenset({"missing", "non_compliant"})
CLAUSE_DIFFERS_FROM_APPROVED_POSITION = "clause_differs_from_approved_position"
_COMPARISON_RENDERINGS = {
    CLAUSE_DIFFERS_FROM_APPROVED_POSITION: "The cited clause differs from the approved position."
}


@dataclass(frozen=True)
class FallbackSuggestionRequest:
    """Evidence and immutable rule text available to a fallback comparison."""

    rule_id: str
    playbook_version_id: str
    finding_result: str
    citation_ids: list[str]
    cited_clause_text: str | None
    preferred_language: str | None
    fallback_language: str | None


@dataclass(frozen=True)
class FallbackSuggestion:
    version: str
    rule_id: str
    playbook_version_id: str
    suggested_language: str | None
    review_recommendation: str
    citation_ids: list[str]
    comparison_kind: str | None
    comparison: str | None
    ai_generated: bool


FallbackModelComparator = Callable[[FallbackSuggestionRequest], Mapping[str, object]]


def suggest_fallback(
    request: FallbackSuggestionRequest,
    *,
    model_comparator: FallbackModelComparator | None = None,
) -> FallbackSuggestion | None:
    """Select an approved position without allowing a model to author policy text."""
    if request.finding_result not in _SUGGESTIBLE_RESULTS:
        return None
    approved_language = _approved_language(request)
    if approved_language is None:
        return _suggestion(request, None, None)
    comparison_kind = _comparison_kind(request, model_comparator)
    return _suggestion(request, approved_language, comparison_kind)


def _approved_language(request: FallbackSuggestionRequest) -> str | None:
    for language in (request.fallback_language, request.preferred_language):
        if isinstance(language, str) and language.strip():
            return language
    return None


def _comparison_kind(
    request: FallbackSuggestionRequest, model_comparator: FallbackModelComparator | None
) -> str | None:
    if model_comparator is None or not request.citation_ids or not request.cited_clause_text:
        return None
    try:
        response: object = model_comparator(request)
    except Exception:
        return None
    if not isinstance(response, Mapping):
        return None
    comparison_kind = response.get("comparison_kind")
    citation_ids = response.get("citation_ids")
    return bounded_comparison_kind(request, comparison_kind, citation_ids)


def bounded_comparison_kind(
    request: FallbackSuggestionRequest,
    comparison_kind: object,
    citation_ids: object,
) -> str | None:
    """Accept only cited comparison facts from the closed policy-safe allowlist."""
    kind = grounded_model_text(
        {"comparison_kind": comparison_kind, "citation_ids": citation_ids},
        text_key="comparison_kind",
        allowed_citation_ids=request.citation_ids,
    )
    return kind if kind in _COMPARISON_RENDERINGS else None


def render_comparison(comparison_kind: str | None) -> str | None:
    """Render model-selected comparison facts without exposing model prose."""
    return _COMPARISON_RENDERINGS.get(comparison_kind) if comparison_kind is not None else None


def _suggestion(
    request: FallbackSuggestionRequest,
    approved_language: str | None,
    comparison_kind: str | None,
) -> FallbackSuggestion:
    return FallbackSuggestion(
        version=FALLBACK_SUGGESTION_PAYLOAD_VERSION,
        rule_id=request.rule_id,
        playbook_version_id=request.playbook_version_id,
        suggested_language=approved_language,
        review_recommendation=(
            "Review the cited clause against the approved fallback language."
            if approved_language is not None
            else "No approved language is available; reviewer assessment is required."
        ),
        citation_ids=list(request.citation_ids),
        comparison_kind=comparison_kind,
        comparison=render_comparison(comparison_kind),
        ai_generated=comparison_kind is not None,
    )
