"""Deterministic alignment of canonical agreement elements across immutable versions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal, cast

AlignmentKind = Literal["matched", "moved", "split", "merged", "added", "removed"]

_MINIMUM_CANDIDATE_SCORE = 0.45
_REVIEW_CONFIDENCE = 0.75
_GROUP_COVERAGE_IMPROVEMENT = 0.15
_GROUP_MINIMUM_COVERAGE = 0.76
_MOVED_POSITION_DISTANCE = 0.25
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class CanonicalElement:
    """A version-scoped section or clause with evidence anchors."""

    element_id: str
    ordinal: int
    heading_path: tuple[str, ...]
    clause_type: str | None
    text: str
    citation_anchor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.element_id:
            raise ValueError("Canonical element id is required")
        if self.ordinal < 0:
            raise ValueError("Canonical element ordinal must be non-negative")
        if not self.text.strip():
            raise ValueError("Canonical element text is required")
        if not self.citation_anchor_ids:
            raise ValueError("Canonical element requires at least one citation anchor")


@dataclass(frozen=True)
class CanonicalVersion:
    """A comparable immutable document version represented by canonical elements."""

    source_checksum: str
    elements: tuple[CanonicalElement, ...]

    def __post_init__(self) -> None:
        if not self.source_checksum:
            raise ValueError("Canonical version source checksum is required")
        ordinals = [element.ordinal for element in self.elements]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("Canonical version element ordinals must be unique")


@dataclass(frozen=True)
class Alignment:
    """One deterministic mapping, or an explicit unmatched element, across two versions."""

    kind: AlignmentKind
    baseline_element_ids: tuple[str, ...]
    target_element_ids: tuple[str, ...]
    confidence: float
    review_required: bool
    rationale: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Alignment confidence must be between zero and one")
        if self.kind == "added" and (self.baseline_element_ids or not self.target_element_ids):
            raise ValueError("Added alignment must contain target elements only")
        if self.kind == "removed" and (not self.baseline_element_ids or self.target_element_ids):
            raise ValueError("Removed alignment must contain baseline elements only")
        if self.kind not in {"added", "removed"} and (
            not self.baseline_element_ids or not self.target_element_ids
        ):
            raise ValueError("Mapped alignment must contain baseline and target elements")


def canonical_version_from_manifest(manifest: Mapping[str, object]) -> CanonicalVersion:
    """Build comparable canonical sections from the existing analysis-artifact shape.

    The adapter is intentionally read-only: persistence and version ownership remain outside the
    alignment engine. It preserves artifact citation anchors so downstream comparison records can
    cite both source versions.
    """

    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("Canonical analysis artifact has no source")
    checksum = _required_string(source, "checksum")
    blocks = _blocks_from_manifest(manifest)
    clause_types_by_anchor = _clause_types_by_anchor(manifest)

    elements: list[CanonicalElement] = []
    heading_path: tuple[str, ...] = ()
    current_entries: list[tuple[str, str]] = []

    def flush() -> None:
        if not current_entries:
            return
        anchor_ids = tuple(anchor_id for anchor_id, _ in current_entries)
        elements.append(
            CanonicalElement(
                element_id=f"section-{checksum[:16]}-{len(elements)}",
                ordinal=len(elements),
                heading_path=heading_path,
                clause_type=_clause_type(anchor_ids, clause_types_by_anchor),
                text="\n".join(text for _, text in current_entries),
                citation_anchor_ids=anchor_ids,
            )
        )
        current_entries.clear()

    for block in blocks:
        text = _required_string(block, "text").strip()
        if not text:
            continue
        anchor_id = _required_string(block, "anchor_id")
        if block.get("kind") == "heading":
            flush()
            heading_path = (*heading_path, text)
        current_entries.append((anchor_id, text))
    flush()
    return CanonicalVersion(source_checksum=checksum, elements=tuple(elements))


def align_versions(baseline: CanonicalVersion, target: CanonicalVersion) -> tuple[Alignment, ...]:
    """Align sections with deterministic text, structure, taxonomy, and position signals."""

    baseline_elements = tuple(sorted(baseline.elements, key=lambda element: element.ordinal))
    target_elements = tuple(sorted(target.elements, key=lambda element: element.ordinal))
    unmatched_baseline = {element.element_id for element in baseline_elements}
    unmatched_target = {element.element_id for element in target_elements}
    results: list[Alignment] = []

    baseline_by_id = {element.element_id: element for element in baseline_elements}
    target_by_id = {element.element_id: element for element in target_elements}

    _align_exact_elements(
        baseline_elements,
        target_elements,
        unmatched_baseline,
        unmatched_target,
        results,
    )
    _align_adjacent_groups(
        baseline_elements,
        target_elements,
        unmatched_baseline,
        unmatched_target,
        results,
    )
    _align_remaining_pairs(
        baseline_elements,
        target_elements,
        unmatched_baseline,
        unmatched_target,
        results,
    )
    results.extend(
        Alignment(
            kind="removed",
            baseline_element_ids=(element.element_id,),
            target_element_ids=(),
            confidence=1.0,
            review_required=False,
            rationale=("No compatible target element was found.",),
        )
        for element in baseline_elements
        if element.element_id in unmatched_baseline
    )
    results.extend(
        Alignment(
            kind="added",
            baseline_element_ids=(),
            target_element_ids=(element.element_id,),
            confidence=1.0,
            review_required=False,
            rationale=("No compatible baseline element was found.",),
        )
        for element in target_elements
        if element.element_id in unmatched_target
    )
    return tuple(
        sorted(
            results,
            key=lambda alignment: _alignment_sort_key(alignment, baseline_by_id, target_by_id),
        )
    )


def _align_exact_elements(
    baseline: tuple[CanonicalElement, ...],
    target: tuple[CanonicalElement, ...],
    unmatched_baseline: set[str],
    unmatched_target: set[str],
    results: list[Alignment],
) -> None:
    targets_by_text: dict[str, list[CanonicalElement]] = {}
    for element in target:
        targets_by_text.setdefault(_normalized_text(element.text), []).append(element)
    for source in baseline:
        if source.element_id not in unmatched_baseline:
            continue
        candidates = [
            element
            for element in targets_by_text.get(_normalized_text(source.text), [])
            if element.element_id in unmatched_target and _compatible_clause_type(source, element)
        ]
        if len(candidates) != 1:
            continue
        candidate = candidates[0]
        unmatched_baseline.remove(source.element_id)
        unmatched_target.remove(candidate.element_id)
        moved = (
            _position_distance(source, candidate, len(baseline), len(target))
            >= _MOVED_POSITION_DISTANCE
        )
        results.append(
            Alignment(
                kind="moved" if moved else "matched",
                baseline_element_ids=(source.element_id,),
                target_element_ids=(candidate.element_id,),
                confidence=1.0,
                review_required=False,
                rationale=(
                    "Normalized text and clause taxonomy are identical.",
                    *("Relative document position changed." if moved else ()),
                ),
            )
        )


def _align_adjacent_groups(
    baseline: tuple[CanonicalElement, ...],
    target: tuple[CanonicalElement, ...],
    unmatched_baseline: set[str],
    unmatched_target: set[str],
    results: list[Alignment],
) -> None:
    for source in baseline:
        if source.element_id not in unmatched_baseline:
            continue
        candidates = _adjacent_pairs(target, unmatched_target)
        best = _best_group_candidate(source, candidates, baseline, target)
        if best is None:
            continue
        first, second, confidence = best
        unmatched_baseline.remove(source.element_id)
        unmatched_target.difference_update((first.element_id, second.element_id))
        results.append(
            Alignment(
                kind="split",
                baseline_element_ids=(source.element_id,),
                target_element_ids=(first.element_id, second.element_id),
                confidence=confidence,
                review_required=confidence < _REVIEW_CONFIDENCE,
                rationale=("One baseline element is covered by two adjacent target elements.",),
            )
        )

    for destination in target:
        if destination.element_id not in unmatched_target:
            continue
        candidates = _adjacent_pairs(baseline, unmatched_baseline)
        best = _best_group_candidate(destination, candidates, target, baseline)
        if best is None:
            continue
        first, second, confidence = best
        unmatched_target.remove(destination.element_id)
        unmatched_baseline.difference_update((first.element_id, second.element_id))
        results.append(
            Alignment(
                kind="merged",
                baseline_element_ids=(first.element_id, second.element_id),
                target_element_ids=(destination.element_id,),
                confidence=confidence,
                review_required=confidence < _REVIEW_CONFIDENCE,
                rationale=("Two adjacent baseline elements are covered by one target element.",),
            )
        )


def _align_remaining_pairs(
    baseline: tuple[CanonicalElement, ...],
    target: tuple[CanonicalElement, ...],
    unmatched_baseline: set[str],
    unmatched_target: set[str],
    results: list[Alignment],
) -> None:
    candidates = sorted(
        (
            (_candidate_score(source, destination, len(baseline), len(target)), source, destination)
            for source in baseline
            if source.element_id in unmatched_baseline
            for destination in target
            if destination.element_id in unmatched_target
            and _compatible_clause_type(source, destination)
        ),
        key=lambda candidate: (-candidate[0], candidate[1].ordinal, candidate[2].ordinal),
    )
    for confidence, source, destination in candidates:
        if confidence < _MINIMUM_CANDIDATE_SCORE:
            break
        if (
            source.element_id not in unmatched_baseline
            or destination.element_id not in unmatched_target
        ):
            continue
        unmatched_baseline.remove(source.element_id)
        unmatched_target.remove(destination.element_id)
        moved = (
            _position_distance(source, destination, len(baseline), len(target))
            >= _MOVED_POSITION_DISTANCE
        )
        results.append(
            Alignment(
                kind="moved" if moved else "matched",
                baseline_element_ids=(source.element_id,),
                target_element_ids=(destination.element_id,),
                confidence=round(confidence, 4),
                review_required=confidence < _REVIEW_CONFIDENCE,
                rationale=(
                    "Text, heading, clause taxonomy, and relative position were compared.",
                    *("Relative document position changed." if moved else ()),
                ),
            )
        )


def _adjacent_pairs(
    elements: tuple[CanonicalElement, ...], unmatched_ids: set[str]
) -> tuple[tuple[CanonicalElement, CanonicalElement], ...]:
    available = [element for element in elements if element.element_id in unmatched_ids]
    return tuple(
        (first, second)
        for first, second in zip(available, available[1:], strict=False)
        if second.ordinal == first.ordinal + 1
    )


def _best_group_candidate(
    source: CanonicalElement,
    candidates: tuple[tuple[CanonicalElement, CanonicalElement], ...],
    source_elements: tuple[CanonicalElement, ...],
    candidate_elements: tuple[CanonicalElement, ...],
) -> tuple[CanonicalElement, CanonicalElement, float] | None:
    best: tuple[CanonicalElement, CanonicalElement, float] | None = None
    for first, second in candidates:
        if not _compatible_clause_type(source, first) and not _compatible_clause_type(
            source, second
        ):
            continue
        combined = _combined_element(first, second)
        coverage = _token_coverage(source.text, combined.text)
        individual_coverage = max(
            _token_coverage(source.text, first.text), _token_coverage(source.text, second.text)
        )
        confidence = max(
            _candidate_score(source, combined, len(source_elements), len(candidate_elements)),
            coverage,
        )
        if (
            coverage < _GROUP_MINIMUM_COVERAGE
            or coverage - individual_coverage < _GROUP_COVERAGE_IMPROVEMENT
        ):
            continue
        if best is None or confidence > best[2]:
            best = (first, second, round(confidence, 4))
    return best


def _combined_element(first: CanonicalElement, second: CanonicalElement) -> CanonicalElement:
    return CanonicalElement(
        element_id=f"{first.element_id}+{second.element_id}",
        ordinal=first.ordinal,
        heading_path=first.heading_path,
        clause_type=first.clause_type if first.clause_type == second.clause_type else None,
        text=f"{first.text}\n{second.text}",
        citation_anchor_ids=(*first.citation_anchor_ids, *second.citation_anchor_ids),
    )


def _candidate_score(
    source: CanonicalElement,
    destination: CanonicalElement,
    source_count: int,
    destination_count: int,
) -> float:
    text_similarity = SequenceMatcher(
        None, _normalized_text(source.text), _normalized_text(destination.text)
    ).ratio()
    heading_similarity = _token_similarity(_heading(source), _heading(destination))
    taxonomy_similarity = _taxonomy_similarity(source.clause_type, destination.clause_type)
    position_similarity = 1.0 - _position_distance(
        source, destination, source_count, destination_count
    )
    return (
        0.65 * text_similarity
        + 0.2 * heading_similarity
        + 0.1 * taxonomy_similarity
        + 0.05 * position_similarity
    )


def _position_distance(
    source: CanonicalElement,
    destination: CanonicalElement,
    source_count: int,
    destination_count: int,
) -> float:
    source_position = source.ordinal / max(source_count - 1, 1)
    destination_position = destination.ordinal / max(destination_count - 1, 1)
    return abs(source_position - destination_position)


def _taxonomy_similarity(first: str | None, second: str | None) -> float:
    if first is None and second is None:
        return 0.5
    if first is None or second is None:
        return 0.25
    return 1.0 if first.casefold() == second.casefold() else 0.0


def _compatible_clause_type(first: CanonicalElement, second: CanonicalElement) -> bool:
    return (
        first.clause_type is None
        or second.clause_type is None
        or (first.clause_type.casefold() == second.clause_type.casefold())
    )


def _token_coverage(source: str, candidate: str) -> float:
    source_tokens = set(_tokens(source))
    if not source_tokens:
        return 0.0
    return len(source_tokens & set(_tokens(candidate))) / len(source_tokens)


def _token_similarity(first: str, second: str) -> float:
    first_tokens = set(_tokens(first))
    second_tokens = set(_tokens(second))
    if not first_tokens and not second_tokens:
        return 1.0
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)


def _heading(element: CanonicalElement) -> str:
    return element.heading_path[-1] if element.heading_path else ""


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(value.casefold()))


def _normalized_text(value: str) -> str:
    return " ".join(_tokens(value))


def _alignment_sort_key(
    alignment: Alignment,
    baseline: Mapping[str, CanonicalElement],
    target: Mapping[str, CanonicalElement],
) -> tuple[int, int]:
    if alignment.baseline_element_ids:
        return (min(baseline[item].ordinal for item in alignment.baseline_element_ids), 0)
    return (min(target[item].ordinal for item in alignment.target_element_ids), 1)


def _blocks_from_manifest(manifest: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    document = manifest.get("document")
    if not isinstance(document, Mapping) or not isinstance(document.get("pages"), list):
        raise ValueError("Canonical analysis artifact has no document pages")
    blocks: list[Mapping[str, object]] = []
    for page in cast(list[object], document["pages"]):
        if not isinstance(page, Mapping) or not isinstance(page.get("blocks"), list):
            raise ValueError("Canonical analysis artifact has malformed page blocks")
        blocks.extend(
            block for block in cast(list[object], page["blocks"]) if isinstance(block, Mapping)
        )
    return tuple(blocks)


def _clause_types_by_anchor(manifest: Mapping[str, object]) -> dict[str, str]:
    value = manifest.get("clauses", [])
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for clause in value:
        if not isinstance(clause, Mapping):
            continue
        category = clause.get("category")
        anchors = clause.get("citation_anchor_ids")
        if not isinstance(category, str) or not isinstance(anchors, list):
            continue
        for anchor in anchors:
            if isinstance(anchor, str):
                result[anchor] = category
    return result


def _clause_type(anchor_ids: tuple[str, ...], by_anchor: Mapping[str, str]) -> str | None:
    candidates = {by_anchor[anchor] for anchor in anchor_ids if anchor in by_anchor}
    return next(iter(candidates)) if len(candidates) == 1 else None


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Canonical analysis artifact has invalid {key}")
    return result
