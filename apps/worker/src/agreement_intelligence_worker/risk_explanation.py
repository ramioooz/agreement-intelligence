from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

RISK_PAYLOAD_VERSION = "playbook-risk.v1"
_REVIEW_REQUIRED_RESULTS = frozenset({"missing", "non_compliant", "needs_review"})


@dataclass(frozen=True)
class RiskExplanationRequest:
    """The bounded evidence a model may use to explain a deterministic finding."""

    rule_severity: str
    rule_rationale: str
    deterministic_result: str
    confidence: float
    citation_ids: list[str]
    cited_clause_text: str | None


@dataclass(frozen=True)
class RiskPayload:
    version: str
    severity: str
    risk_rationale: str
    risk_confidence: float
    review_status: str
    citation_ids: list[str]
    model_explanation: str | None


RiskModelExplainer = Callable[[RiskExplanationRequest], Mapping[str, object]]


def explain_risk(
    request: RiskExplanationRequest,
    *,
    model_explainer: RiskModelExplainer | None = None,
) -> RiskPayload:
    """Create a policy-bounded risk payload from a deterministic finding.

    Optional model prose is accepted only when it cites exactly the supplied clause
    evidence. The rule-owned severity and deterministic review status are never
    model-controlled.
    """
    model_explanation = _model_explanation(request, model_explainer)
    return RiskPayload(
        version=RISK_PAYLOAD_VERSION,
        severity=request.rule_severity,
        risk_rationale=_rationale(request),
        risk_confidence=_confidence(request.confidence),
        review_status=_review_status(request.deterministic_result),
        citation_ids=list(request.citation_ids),
        model_explanation=model_explanation,
    )


def _rationale(request: RiskExplanationRequest) -> str:
    rationale = request.rule_rationale.strip()
    return rationale or "The deterministic finding requires reviewer assessment."


def _confidence(value: float) -> float:
    return min(1.0, max(0.0, value))


def _review_status(result: str) -> str:
    return "review_required" if result in _REVIEW_REQUIRED_RESULTS else "complete"


def _model_explanation(
    request: RiskExplanationRequest, model_explainer: RiskModelExplainer | None
) -> str | None:
    if model_explainer is None or not request.citation_ids or not request.cited_clause_text:
        return None
    try:
        response: object = model_explainer(request)
    except Exception:
        return None
    return grounded_model_text(
        response,
        text_key="rationale",
        allowed_citation_ids=request.citation_ids,
    )


def grounded_model_text(
    response: object,
    *,
    text_key: str,
    allowed_citation_ids: list[str],
) -> str | None:
    """Return model text only when its complete citation payload is grounded."""
    try:
        if not isinstance(response, Mapping):
            return None
        if set(response) != {text_key, "citation_ids"}:
            return None
        rationale = response.get(text_key)
        citation_ids = response.get("citation_ids")
        if not isinstance(rationale, str) or not rationale.strip():
            return None
        if not isinstance(citation_ids, list) or not all(
            isinstance(item, str) for item in citation_ids
        ):
            return None
        if not citation_ids or not set(citation_ids).issubset(allowed_citation_ids):
            return None
        return rationale.strip()
    except Exception:
        return None
