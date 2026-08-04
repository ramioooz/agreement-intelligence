"""Framework-neutral evaluation for agreement-version comparison results.

The frozen dataset deliberately describes expected alignment, textual change, materiality,
and citation outcomes without importing the runtime comparison service.  When the runtime
contracts are stable, its adapter only needs to emit the small observation shape accepted
by :func:`evaluate_version_comparisons`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast


class AlignmentLabel(TypedDict):
    id: str
    kind: str
    review_required: bool


class ExpectedChange(TypedDict):
    id: str
    change_type: str
    severity: str
    citation_ids: list[str]


class ComparisonObservationChange(ExpectedChange):
    accepted: bool


class ComparisonObservation(TypedDict):
    case_id: str
    alignments: list[AlignmentLabel]
    changes: list[ComparisonObservationChange]
    unauthorized_evidence_ids: list[str]


class ComparisonEvaluationMetrics(TypedDict):
    alignment_f1: float
    alignment_precision: float
    alignment_recall: float
    citation_precision: float
    critical_material_change_recall: float
    deterministic_change_accuracy: float
    unauthorized_evidence_count: int
    unsupported_accepted_claims: int


class BaselineResult(TypedDict):
    passed: bool
    failures: list[str]


class ComparisonEvaluationReport(TypedDict):
    dataset_version: str
    cases: int
    metrics: ComparisonEvaluationMetrics
    baseline: BaselineResult


@dataclass(frozen=True)
class ComparisonEvaluationDataset:
    version: str
    cases: dict[str, Mapping[str, object]]
    baseline: Mapping[str, object]


_DEFAULT_DATASET = (
    Path(__file__).parents[2]
    / "tests"
    / "golden"
    / "version-comparison"
    / "v1"
    / "version-pairs.json"
)
_ALIGNMENT_KINDS = {"matched", "moved", "split", "merged", "added", "removed"}
_CHANGE_TYPES = {"added", "removed", "modified", "moved", "split", "merged"}
_SEVERITIES = {"low", "medium", "high", "critical"}


def load_dataset(path: Path = _DEFAULT_DATASET) -> ComparisonEvaluationDataset:
    payload = _object(json.loads(path.read_text()), "dataset")
    version = _string(payload.get("version"), "dataset version")
    cases: dict[str, Mapping[str, object]] = {}
    for value in _list(payload.get("cases"), "cases"):
        case = _object(value, "case")
        case_id = _string(case.get("id"), "case id")
        if case_id in cases:
            raise ValueError(f"Duplicate evaluation case id: {case_id}")
        _alignments(case.get("expected_alignments"), f"case {case_id} alignments")
        _expected_changes(case.get("expected_changes"), f"case {case_id} changes")
        cases[case_id] = case
    if not cases:
        raise ValueError("Evaluation dataset must include at least one case")
    return ComparisonEvaluationDataset(
        version=version,
        cases=cases,
        baseline=_object(payload.get("accepted_baseline"), "accepted baseline"),
    )


def load_observations(
    path: Path, dataset: ComparisonEvaluationDataset
) -> list[ComparisonObservation]:
    payload = _object(json.loads(path.read_text()), "results")
    if _string(payload.get("dataset_version"), "results dataset version") != dataset.version:
        raise ValueError("Results dataset_version does not match the evaluation dataset")
    return [_observation(value) for value in _list(payload.get("observations"), "observations")]


def evaluate_version_comparisons(
    dataset: ComparisonEvaluationDataset, observations: Sequence[ComparisonObservation]
) -> ComparisonEvaluationReport:
    observations_by_id = _observations_by_id(dataset, observations)
    alignment_expected = alignment_found = alignment_returned = 0
    change_expected = change_correct = 0
    critical_expected = critical_found = 0
    citation_valid = citation_returned = 0
    unsupported_claims = unauthorized_evidence_count = 0

    for case_id, case in dataset.cases.items():
        observation = observations_by_id[case_id]
        expected_alignments = {
            _alignment_key(item)
            for item in _alignments(case.get("expected_alignments"), f"case {case_id} alignments")
        }
        actual_alignments = {_alignment_key(item) for item in observation["alignments"]}
        alignment_expected += len(expected_alignments)
        alignment_found += len(expected_alignments & actual_alignments)
        alignment_returned += len(actual_alignments)

        expected_changes = {
            expected_change["id"]: expected_change
            for expected_change in _expected_changes(
                case.get("expected_changes"), f"case {case_id} changes"
            )
        }
        change_expected += len(expected_changes)
        for change in observation["changes"]:
            expected = expected_changes.get(change["id"])
            citations = set(change["citation_ids"])
            if expected is None:
                if change["accepted"]:
                    unsupported_claims += 1
                citation_returned += len(citations)
                continue
            if (
                change["change_type"] == expected["change_type"]
                and change["severity"] == expected["severity"]
            ):
                change_correct += 1
            expected_citations = set(expected["citation_ids"])
            citation_returned += len(citations)
            citation_valid += len(citations & expected_citations)
            if change["accepted"] and not expected_citations.issubset(citations):
                unsupported_claims += 1
            if expected["severity"] == "critical" and change["severity"] == "critical":
                critical_found += 1
        critical_expected += sum(
            1 for change in expected_changes.values() if change["severity"] == "critical"
        )
        unauthorized_evidence_count += len(observation["unauthorized_evidence_ids"])

    precision = _ratio(alignment_found, alignment_returned)
    recall = _ratio(alignment_found, alignment_expected)
    metrics: ComparisonEvaluationMetrics = {
        "alignment_f1": _f1(precision, recall),
        "alignment_precision": precision,
        "alignment_recall": recall,
        "citation_precision": _ratio(citation_valid, citation_returned),
        "critical_material_change_recall": _ratio(critical_found, critical_expected),
        "deterministic_change_accuracy": _ratio(change_correct, change_expected),
        "unauthorized_evidence_count": unauthorized_evidence_count,
        "unsupported_accepted_claims": unsupported_claims,
    }
    return {
        "dataset_version": dataset.version,
        "cases": len(dataset.cases),
        "metrics": metrics,
        "baseline": _compare_baseline(metrics, dataset.baseline),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agreement-version comparison quality.")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    print(
        json.dumps(
            evaluate_version_comparisons(dataset, load_observations(args.results, dataset)),
            sort_keys=True,
        )
    )


def _observations_by_id(
    dataset: ComparisonEvaluationDataset, observations: Sequence[ComparisonObservation]
) -> dict[str, ComparisonObservation]:
    identifiers = [observation["case_id"] for observation in observations]
    duplicates = sorted(
        {identifier for identifier in identifiers if identifiers.count(identifier) > 1}
    )
    if duplicates:
        raise ValueError(f"Results contain duplicate case ids: {duplicates}")
    observations_by_id = {observation["case_id"]: observation for observation in observations}
    unexpected = set(observations_by_id) - set(dataset.cases)
    missing = set(dataset.cases) - set(observations_by_id)
    if unexpected or missing:
        raise ValueError(
            f"Results must include every dataset case; missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    return observations_by_id


def _observation(value: object) -> ComparisonObservation:
    item = _object(value, "observation")
    return {
        "case_id": _string(item.get("case_id"), "observation case id"),
        "alignments": _alignments(item.get("alignments"), "observation alignments"),
        "changes": _observation_changes(item.get("changes"), "observation changes"),
        "unauthorized_evidence_ids": _strings(
            item.get("unauthorized_evidence_ids"), "observation unauthorized evidence ids"
        ),
    }


def _alignments(value: object, label: str) -> list[AlignmentLabel]:
    labels: list[AlignmentLabel] = []
    for item in _list(value, label):
        alignment = _object(item, f"{label} item")
        kind = _string(alignment.get("kind"), f"{label} kind")
        if kind not in _ALIGNMENT_KINDS:
            raise ValueError(f"{label} has unsupported alignment kind: {kind}")
        review_required = alignment.get("review_required")
        if not isinstance(review_required, bool):
            raise ValueError(f"{label} review_required must be a boolean")
        labels.append(
            {
                "id": _string(alignment.get("id"), f"{label} id"),
                "kind": kind,
                "review_required": review_required,
            }
        )
    return labels


def _expected_changes(value: object, label: str) -> list[ExpectedChange]:
    changes: list[ExpectedChange] = []
    for item in _list(value, label):
        change = _object(item, f"{label} item")
        changes.append(_change(change, label))
    return changes


def _observation_changes(value: object, label: str) -> list[ComparisonObservationChange]:
    changes: list[ComparisonObservationChange] = []
    for item in _list(value, label):
        change = _change(_object(item, f"{label} item"), label)
        accepted = _object(item, f"{label} item").get("accepted")
        if not isinstance(accepted, bool):
            raise ValueError(f"{label} accepted must be a boolean")
        changes.append({**change, "accepted": accepted})
    return changes


def _change(change: Mapping[str, object], label: str) -> ExpectedChange:
    change_type = _string(change.get("change_type"), f"{label} change_type")
    if change_type not in _CHANGE_TYPES:
        raise ValueError(f"{label} has unsupported change_type: {change_type}")
    severity = _string(change.get("severity"), f"{label} severity")
    if severity not in _SEVERITIES:
        raise ValueError(f"{label} has unsupported severity: {severity}")
    return {
        "id": _string(change.get("id"), f"{label} id"),
        "change_type": change_type,
        "severity": severity,
        "citation_ids": _strings(change.get("citation_ids"), f"{label} citation_ids"),
    }


def _alignment_key(value: AlignmentLabel) -> tuple[str, str, bool]:
    return value["id"], value["kind"], value["review_required"]


def _compare_baseline(
    metrics: ComparisonEvaluationMetrics, baseline: Mapping[str, object]
) -> BaselineResult:
    failures: list[str] = []
    for metric_name, threshold in baseline.items():
        metric = metrics.get(metric_name)
        threshold_value = _object(threshold, f"baseline {metric_name}")
        minimum = threshold_value.get("minimum")
        maximum = threshold_value.get("maximum")
        if minimum is not None and (
            not isinstance(minimum, int | float)
            or not isinstance(metric, int | float)
            or metric < minimum
        ):
            failures.append(f"{metric_name} is below its accepted minimum")
        if maximum is not None and (
            not isinstance(maximum, int | float)
            or not isinstance(metric, int | float)
            or metric > maximum
        ):
            failures.append(f"{metric_name} exceeds its accepted maximum")
    return {"passed": not failures, "failures": failures}


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return cast(list[object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _strings(value: object, label: str) -> list[str]:
    return [_string(item, label) for item in _list(value, label)]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


if __name__ == "__main__":
    main()
