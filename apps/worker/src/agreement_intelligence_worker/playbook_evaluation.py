from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

EvaluationMethod = Literal["deterministic", "semantic"]
PolicyType = Literal["required", "prohibited", "preferred"]

_MINIMUM_CONFIDENCE = 0.8


class FindingResult(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    NON_COMPLIANT = "non_compliant"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class PlaybookRule:
    id: str
    clause_type: str
    policy_type: PolicyType
    preferred_language: str | None
    severity: str
    evaluation_method: EvaluationMethod = "deterministic"
    semantic_assessment_permitted: bool = False


@dataclass(frozen=True)
class EvaluatedFinding:
    rule_id: str
    result: FindingResult
    severity: str
    confidence: float
    method: EvaluationMethod
    citation_ids: list[str]
    extraction_version: str


SemanticAssessor = Callable[[PlaybookRule, Mapping[str, object]], FindingResult]


def evaluate_playbook(
    rules: Iterable[PlaybookRule],
    analysis: Mapping[str, object],
    *,
    semantic_assessor: SemanticAssessor | None = None,
) -> list[EvaluatedFinding]:
    """Evaluate extracted clauses deterministically before optional semantic assessment.

    An extraction is evidence only when it has a citation and meets the confidence
    floor. Missing or uncertain evidence remains explicitly reviewable.
    """
    clauses = _clauses(analysis)
    findings: list[EvaluatedFinding] = []
    for rule in rules:
        candidates = [
            clause
            for clause in clauses
            if _normalized(clause.get("category")) == _normalized(rule.clause_type)
        ]
        finding = _deterministic_finding(rule, candidates)
        if _may_assess_semantically(rule, finding, candidates, semantic_assessor):
            assert semantic_assessor is not None
            semantic_result = semantic_assessor(rule, candidates[0])
            # Model assistance can flag ambiguity/deviation but cannot create compliance.
            if semantic_result in {FindingResult.NEEDS_REVIEW, FindingResult.NON_COMPLIANT}:
                finding = EvaluatedFinding(
                    rule_id=finding.rule_id,
                    result=semantic_result,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    method="semantic",
                    citation_ids=finding.citation_ids,
                    extraction_version=finding.extraction_version,
                )
        findings.append(finding)
    return findings


def _deterministic_finding(
    rule: PlaybookRule, candidates: list[Mapping[str, object]]
) -> EvaluatedFinding:
    if not candidates:
        return _finding(rule, FindingResult.NEEDS_REVIEW, 0.0, [], "unknown")
    clause = max(candidates, key=_confidence)
    confidence = _confidence(clause)
    citations = _citations(clause)
    extraction_version = _string(clause.get("extraction_version"), "unknown")
    if confidence < _MINIMUM_CONFIDENCE or not citations:
        return _finding(rule, FindingResult.NEEDS_REVIEW, confidence, citations, extraction_version)

    source_text = _string(clause.get("source_text"), "").casefold()
    expected_language = (rule.preferred_language or "").strip().casefold()
    matches_policy_language = bool(expected_language) and expected_language in source_text
    if rule.policy_type == "prohibited":
        result = FindingResult.NON_COMPLIANT if matches_policy_language else FindingResult.SATISFIED
    elif matches_policy_language:
        result = FindingResult.SATISFIED
    else:
        result = FindingResult.NEEDS_REVIEW
    return _finding(rule, result, confidence, citations, extraction_version)


def _may_assess_semantically(
    rule: PlaybookRule,
    finding: EvaluatedFinding,
    candidates: list[Mapping[str, object]],
    semantic_assessor: SemanticAssessor | None,
) -> bool:
    return (
        semantic_assessor is not None
        and rule.evaluation_method == "semantic"
        and rule.semantic_assessment_permitted
        and finding.result is FindingResult.NEEDS_REVIEW
        and bool(candidates)
        and bool(finding.citation_ids)
        and finding.confidence >= _MINIMUM_CONFIDENCE
    )


def _finding(
    rule: PlaybookRule,
    result: FindingResult,
    confidence: float,
    citation_ids: list[str],
    extraction_version: str,
) -> EvaluatedFinding:
    return EvaluatedFinding(
        rule_id=rule.id,
        result=result,
        severity=rule.severity,
        confidence=confidence,
        method="deterministic",
        citation_ids=citation_ids,
        extraction_version=extraction_version,
    )


def _clauses(analysis: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = analysis.get("clauses", [])
    if not isinstance(value, list):
        return []
    return [clause for clause in value if isinstance(clause, Mapping)]


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _string(value, "").casefold()).strip("_")


def _confidence(clause: Mapping[str, object]) -> float:
    value = clause.get("confidence")
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _citations(clause: Mapping[str, object]) -> list[str]:
    value = clause.get("citation_anchor_ids")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) else default
