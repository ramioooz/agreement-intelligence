from __future__ import annotations

from collections.abc import Mapping

from agreement_intelligence_worker.playbook_evaluation import (
    FindingResult,
    PlaybookRule,
    evaluate_playbook,
)


def test_required_clause_with_grounded_preferred_language_is_satisfied() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="required-liability",
                clause_type="limitation_of_liability",
                policy_type="required",
                preferred_language="liability is capped at fees paid",
                severity="high",
            )
        ],
        _analysis(
            _clause(
                "limitation_of_liability",
                "Liability is capped at fees paid in the prior 12 months.",
            )
        ),
    )

    assert findings[0].result is FindingResult.SATISFIED
    assert findings[0].method == "deterministic"
    assert findings[0].citation_ids == ["citation-liability"]


def test_required_clause_without_extracted_evidence_requires_human_review() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="required-termination",
                clause_type="termination",
                policy_type="required",
                preferred_language="either party may terminate",
                severity="high",
            )
        ],
        _analysis(),
    )

    assert findings[0].result is FindingResult.NEEDS_REVIEW
    assert findings[0].citation_ids == []
    assert findings[0].confidence == 0.0


def test_provider_only_clause_cannot_turn_deterministic_absence_into_compliance() -> None:
    provider_clause = _clause(
        "termination",
        "Either party may terminate with 30 days' notice.",
        confidence=1.0,
    )
    provider_clause["extraction_version"] = "provider-hybrid.v1"

    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="required-termination",
                clause_type="termination",
                policy_type="required",
                preferred_language="either party may terminate",
                severity="high",
            )
        ],
        _analysis(provider_clause),
    )

    assert findings[0].result is FindingResult.NEEDS_REVIEW
    assert findings[0].citation_ids == []
    assert findings[0].confidence == 0.0


def test_prohibited_language_in_grounded_clause_is_non_compliant() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="prohibited-unlimited-liability",
                clause_type="limitation_of_liability",
                policy_type="prohibited",
                preferred_language="unlimited liability",
                severity="critical",
            )
        ],
        _analysis(_clause("limitation_of_liability", "The supplier accepts unlimited liability.")),
    )

    assert findings[0].result is FindingResult.NON_COMPLIANT
    assert findings[0].severity == "critical"


def test_liability_extraction_alias_matches_limitation_of_liability_rule() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="prohibited-unlimited-liability",
                clause_type="limitation_of_liability",
                policy_type="prohibited",
                preferred_language="unlimited liability",
                severity="critical",
            )
        ],
        _analysis(_clause("liability", "The supplier accepts unlimited liability.")),
    )

    assert findings[0].result is FindingResult.NON_COMPLIANT
    assert findings[0].citation_ids == ["citation-liability"]


def test_satisfied_findings_do_not_receive_fallback_suggestions() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="required-liability",
                clause_type="limitation_of_liability",
                policy_type="required",
                preferred_language="liability is capped at fees paid",
                fallback_language="Liability is capped at USD 100,000.",
                severity="high",
            )
        ],
        _analysis(
            _clause(
                "limitation_of_liability",
                "Liability is capped at fees paid in the prior 12 months.",
            )
        ),
        playbook_version_id="version-4",
    )

    assert findings[0].result is FindingResult.SATISFIED
    assert findings[0].fallback_suggestions == []


def test_prohibited_rule_without_policy_language_requires_human_review() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="prohibited-unspecified",
                clause_type="limitation_of_liability",
                policy_type="prohibited",
                preferred_language=None,
                severity="critical",
            )
        ],
        _analysis(_clause("limitation_of_liability", "The supplier accepts unlimited liability.")),
    )

    assert findings[0].result is FindingResult.NEEDS_REVIEW


def test_semantic_assessment_receives_the_persisted_highest_confidence_candidate() -> None:
    observed: dict[str, object] = {}

    def semantic_assessor(rule: PlaybookRule, clause: Mapping[str, object]) -> FindingResult:
        observed["rule"] = rule
        observed["citation_ids"] = clause["citation_anchor_ids"]
        return FindingResult.NEEDS_REVIEW

    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="semantic-liability",
                clause_type="limitation_of_liability",
                policy_type="required",
                preferred_language="liability is capped at fees paid",
                severity="high",
                evaluation_method="semantic",
                semantic_assessment_permitted=True,
            )
        ],
        _analysis(
            {
                **_clause(
                    "limitation_of_liability", "An unclear liability position.", confidence=0.81
                ),
                "citation_anchor_ids": ["citation-low"],
            },
            {
                **_clause(
                    "limitation_of_liability",
                    "Another unclear liability position.",
                    confidence=0.95,
                ),
                "citation_anchor_ids": ["citation-high"],
            },
        ),
        semantic_assessor=semantic_assessor,
    )

    assert findings[0].method == "semantic"
    assert findings[0].citation_ids == ["citation-high"]
    assert observed["citation_ids"] == ["citation-high"]


def test_low_confidence_clause_requires_human_review_even_when_text_matches() -> None:
    findings = evaluate_playbook(
        [
            PlaybookRule(
                id="required-confidentiality",
                clause_type="confidentiality",
                policy_type="required",
                preferred_language="keep confidential",
                severity="medium",
            )
        ],
        _analysis(
            _clause(
                "confidentiality",
                "Each party must keep confidential information confidential.",
                confidence=0.49,
            )
        ),
    )

    assert findings[0].result is FindingResult.NEEDS_REVIEW
    assert findings[0].citation_ids == ["citation-confidentiality"]


def _analysis(*clauses: dict[str, object]) -> dict[str, object]:
    return {"clauses": list(clauses)}


def _clause(clause_type: str, source_text: str, *, confidence: float = 0.9) -> dict[str, object]:
    return {
        "category": clause_type,
        "source_text": source_text,
        "confidence": confidence,
        "citation_anchor_ids": [f"citation-{clause_type.removeprefix('limitation_of_')}"],
        "extraction_version": "clause-rules.v1",
    }
