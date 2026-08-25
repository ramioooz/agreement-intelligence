"""Deterministic, citation-preserving assessment of version changes.

This module deliberately owns no persistence or queue transport.  It accepts the
stable, version-scoped evidence prepared by the alignment layer and returns a
serializable result which comparison-run persistence can store unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

ChangeType = Literal["added", "removed", "modified", "moved", "split", "merged"]
Severity = Literal["low", "medium", "high", "critical"]
DiffKind = Literal["equal", "insert", "delete", "replace"]

_TOKEN_PATTERN = re.compile(r"\S+")
_CONCEPT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("liability", re.compile(r"\bliabilit(?:y|ies)\b|\bcap(?:ped)?\b", re.IGNORECASE)),
    ("indemnity", re.compile(r"\bindemn(?:ity|if(?:y|ies|ication))\b", re.IGNORECASE)),
    ("termination", re.compile(r"\bterminat(?:e|es|ed|ion)\b", re.IGNORECASE)),
    ("governing_law", re.compile(r"\bgoverning law\b|\bjuri[sd]iction\b", re.IGNORECASE)),
    ("parties", re.compile(r"\bparty\b|\bparties\b", re.IGNORECASE)),
    ("obligation", re.compile(r"\bshall\b|\bmust\b|\bwill\b|\brequired\b", re.IGNORECASE)),
)
_NUMBER_PATTERN = re.compile(r"(?:\b(?:USD|AED|EUR|GBP)\s*)?\b\d[\d,]*(?:\.\d+)?\b")
_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_SEVERITY_ORDER: dict[Severity, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class MaterialityCandidate:
    """One aligned (or explicitly unmatched) version change and its source evidence."""

    change_type: ChangeType
    baseline_text: str
    target_text: str
    baseline_citation_ids: tuple[str, ...]
    target_citation_ids: tuple[str, ...]
    alignment_confidence: float
    review_required: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.alignment_confidence <= 1.0:
            raise ValueError("Alignment confidence must be between zero and one")
        if not self.baseline_citation_ids and not self.target_citation_ids:
            raise ValueError("Materiality candidates require source citations")
        if self.change_type == "added" and self.baseline_text:
            raise ValueError("An added change cannot contain baseline text")
        if self.change_type == "removed" and self.target_text:
            raise ValueError("A removed change cannot contain target text")


@dataclass(frozen=True)
class WordDiffOperation:
    kind: DiffKind
    baseline_tokens: tuple[str, ...]
    target_tokens: tuple[str, ...]


@dataclass(frozen=True)
class MaterialityResult:
    schema_version: str
    change_type: ChangeType
    severity: Severity
    legal_concepts: tuple[str, ...]
    rationale: str
    confidence: float
    review_required: bool
    baseline_citation_ids: tuple[str, ...]
    target_citation_ids: tuple[str, ...]
    word_diff: tuple[WordDiffOperation, ...]
    model_rationale: str | None
    provider_provenance: dict[str, object] | None


def assess_materiality(candidate: MaterialityCandidate) -> MaterialityResult:
    """Return a deterministic assessment with all textual and citation evidence retained.

    Provider enrichment is intentionally added by the queue-backed comparison service after
    persistence contracts are available.  That adapter may only raise severity and append a
    cited rationale; this deterministic output remains the legal baseline.
    """

    concepts = _concepts(candidate.baseline_text, candidate.target_text)
    severity = _severity(candidate, concepts)
    review_required = (
        candidate.review_required or candidate.alignment_confidence < 0.75 or severity == "critical"
    )
    return MaterialityResult(
        schema_version="version-materiality.v1",
        change_type=candidate.change_type,
        severity=severity,
        legal_concepts=concepts,
        rationale=_rationale(candidate, concepts, severity),
        confidence=round(candidate.alignment_confidence, 4),
        review_required=review_required,
        baseline_citation_ids=candidate.baseline_citation_ids,
        target_citation_ids=candidate.target_citation_ids,
        word_diff=word_diff(candidate.baseline_text, candidate.target_text),
        model_rationale=None,
        provider_provenance=None,
    )


def word_diff(baseline_text: str, target_text: str) -> tuple[WordDiffOperation, ...]:
    """Return deterministic word-level operations for structured comparison panes."""

    baseline_tokens = tuple(_TOKEN_PATTERN.findall(baseline_text))
    target_tokens = tuple(_TOKEN_PATTERN.findall(target_text))
    matcher = SequenceMatcher(a=baseline_tokens, b=target_tokens, autojunk=False)
    return tuple(
        WordDiffOperation(
            kind=tag,
            baseline_tokens=baseline_tokens[baseline_start:baseline_end],
            target_tokens=target_tokens[target_start:target_end],
        )
        for tag, baseline_start, baseline_end, target_start, target_end in matcher.get_opcodes()
        if tag != "equal" or baseline_tokens[baseline_start:baseline_end]
    )


def augment_materiality(
    deterministic: MaterialityResult,
    payload: object,
    *,
    provider_provenance: Mapping[str, object],
) -> MaterialityResult:
    """Accept a model interpretation only when it remains fully cited and non-downgrading.

    The persisted deterministic rationale, word diff, concepts, and evidence are immutable from
    the model's perspective. Invalid provider output produces the untouched baseline.
    """

    if not isinstance(payload, Mapping) or set(payload) != {
        "severity",
        "rationale",
        "citation_ids",
    }:
        return deterministic
    severity = payload.get("severity")
    rationale = payload.get("rationale")
    citation_ids = payload.get("citation_ids")
    allowed_citations = set(
        (*deterministic.baseline_citation_ids, *deterministic.target_citation_ids)
    )
    if (
        not isinstance(severity, str)
        or severity not in _SEVERITY_ORDER
        or not isinstance(rationale, str)
        or not rationale.strip()
        or not isinstance(citation_ids, list)
        or not citation_ids
        or not all(isinstance(citation_id, str) for citation_id in citation_ids)
        or not set(citation_ids).issubset(allowed_citations)
        or _SEVERITY_ORDER[severity] < _SEVERITY_ORDER[deterministic.severity]
    ):
        return deterministic
    return MaterialityResult(
        **{
            **deterministic.__dict__,
            "severity": severity,
            "model_rationale": rationale.strip(),
            "provider_provenance": _safe_provenance(provider_provenance),
        }
    )


def _concepts(baseline_text: str, target_text: str) -> tuple[str, ...]:
    text = f"{baseline_text}\n{target_text}"
    concepts = [name for name, pattern in _CONCEPT_PATTERNS if pattern.search(text)]
    if _NUMBER_PATTERN.search(text):
        concepts.append("numbers")
    if _DATE_PATTERN.search(text):
        concepts.append("dates")
    return tuple(concepts) or ("cosmetic",)


def _severity(candidate: MaterialityCandidate, concepts: tuple[str, ...]) -> Severity:
    if candidate.change_type in {"added", "removed"} and {
        "liability",
        "indemnity",
        "termination",
        "governing_law",
    } & set(concepts):
        return "critical"
    if "liability" in concepts and "numbers" in concepts:
        return "critical"
    if {"liability", "indemnity", "termination", "governing_law"} & set(concepts):
        return "high"
    if {"parties", "obligation", "numbers", "dates"} & set(concepts):
        return "medium"
    return "low"


def _rationale(
    candidate: MaterialityCandidate, concepts: tuple[str, ...], severity: Severity
) -> str:
    concept_text = ", ".join(concepts)
    if candidate.change_type == "moved" and candidate.baseline_text == candidate.target_text:
        return f"The clause moved without a textual change; detected concepts: {concept_text}."
    return (
        f"Deterministic {candidate.change_type} change assessed as {severity}; "
        f"detected concepts: {concept_text}."
    )


def _safe_provenance(value: Mapping[str, object]) -> dict[str, object]:
    """Store only operational metadata, never request or response text."""

    allowed = {
        "provider",
        "endpoint_kind",
        "model",
        "configuration_version",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
        "retry_outcome",
        "fallback_outcome",
        "safe_failure_reason",
        "schema_checksum",
        "model_route",
    }
    return {key: value[key] for key in allowed & set(value)}
