from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import TypedDict, cast


class AcceptedClaim(TypedDict):
    claim_id: str
    citation_anchor_ids: list[str]


class EvaluationObservation(TypedDict):
    question_id: str
    retrieved_anchor_ids: list[str]
    citation_anchor_ids: list[str]
    accepted_claims: list[AcceptedClaim]
    unauthorized_retrieved_anchor_ids: list[str]
    latency_ms: float
    cost_usd: float


class EvaluationMetrics(TypedDict):
    retrieval_recall_at_5: float
    citation_precision: float
    citation_recall: float
    unsupported_accepted_claims: int
    unsupported_accepted_claim_rate: float
    unauthorized_retrieval_count: int
    latency_ms_p95: float
    cost_usd_total: float


class BaselineResult(TypedDict):
    passed: bool
    failures: list[str]


class RetrievalEvaluationReport(TypedDict):
    dataset_version: str
    cases: int
    metrics: EvaluationMetrics
    baseline: BaselineResult


@dataclass(frozen=True)
class EvaluationDataset:
    version: str
    questions: dict[str, Mapping[str, object]]
    baseline: Mapping[str, object]


_DEFAULT_DATASET = (
    Path(__file__).parents[2] / "tests" / "golden" / "retrieval-quality" / "v1" / "questions.json"
)
_REQUIRED_CATEGORIES = {
    "answerable",
    "unanswerable",
    "ambiguous_conflicting",
    "adversarial_prompt_injection",
    "permission_sensitive",
}


def load_dataset(path: Path = _DEFAULT_DATASET) -> EvaluationDataset:
    payload = _object(json.loads(path.read_text()), "dataset")
    version = _string(payload.get("version"), "dataset version")
    questions_value = _list(payload.get("questions"), "questions")
    questions: dict[str, Mapping[str, object]] = {}
    categories: set[str] = set()
    for item in questions_value:
        question = _object(item, "question")
        question_id = _string(question.get("id"), "question id")
        if question_id in questions:
            raise ValueError(f"Duplicate evaluation question id: {question_id}")
        categories.add(_string(question.get("category"), f"question {question_id} category"))
        _string_list(question.get("expected_retrieval_anchor_ids"), question_id)
        _string_list(question.get("expected_citation_anchor_ids"), question_id)
        _claims(question.get("expected_claims"), question_id)
        questions[question_id] = question
    missing_categories = _REQUIRED_CATEGORIES - categories
    if missing_categories:
        raise ValueError(f"Dataset is missing required categories: {sorted(missing_categories)}")
    return EvaluationDataset(
        version=version,
        questions=questions,
        baseline=_object(payload.get("accepted_baseline"), "accepted baseline"),
    )


def evaluate_retrieval_quality(
    dataset: EvaluationDataset, observations: Sequence[EvaluationObservation]
) -> RetrievalEvaluationReport:
    observations_by_id = {observation["question_id"]: observation for observation in observations}
    unexpected = set(observations_by_id) - set(dataset.questions)
    missing = set(dataset.questions) - set(observations_by_id)
    if unexpected or missing:
        raise ValueError(
            f"Results must include every dataset question; missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )

    retrieval_relevant = 0
    retrieval_found = 0
    citation_expected = 0
    citation_found = 0
    citation_returned = 0
    unsupported_claims = 0
    accepted_claims = 0
    unauthorized_retrieval_count = 0
    latencies: list[float] = []
    costs: list[float] = []
    for question_id, question in dataset.questions.items():
        observation = observations_by_id[question_id]
        expected_retrieval = set(
            _string_list(question.get("expected_retrieval_anchor_ids"), question_id)
        )
        expected_citations = set(
            _string_list(question.get("expected_citation_anchor_ids"), question_id)
        )
        retrieved = set(observation["retrieved_anchor_ids"][:5])
        citations = set(observation["citation_anchor_ids"])
        retrieval_relevant += len(expected_retrieval)
        retrieval_found += len(expected_retrieval & retrieved)
        citation_expected += len(expected_citations)
        citation_found += len(expected_citations & citations)
        citation_returned += len(citations)
        expected_claims = {
            claim["claim_id"]: set(claim["citation_anchor_ids"])
            for claim in _claims(question.get("expected_claims"), question_id)
        }
        for claim in observation["accepted_claims"]:
            accepted_claims += 1
            expected_claim_citations = expected_claims.get(claim["claim_id"], set())
            if not (set(claim["citation_anchor_ids"]) & expected_claim_citations):
                unsupported_claims += 1
        unauthorized_retrieval_count += len(observation["unauthorized_retrieved_anchor_ids"])
        latencies.append(observation["latency_ms"])
        costs.append(observation["cost_usd"])

    metrics: EvaluationMetrics = {
        "retrieval_recall_at_5": _ratio(retrieval_found, retrieval_relevant),
        "citation_precision": _ratio(citation_found, citation_returned),
        "citation_recall": _ratio(citation_found, citation_expected),
        "unsupported_accepted_claims": unsupported_claims,
        "unsupported_accepted_claim_rate": _ratio(unsupported_claims, accepted_claims),
        "unauthorized_retrieval_count": unauthorized_retrieval_count,
        "latency_ms_p95": _p95(latencies),
        "cost_usd_total": round(sum(costs), 6),
    }
    return {
        "dataset_version": dataset.version,
        "cases": len(dataset.questions),
        "metrics": metrics,
        "baseline": _compare_baseline(metrics, dataset.baseline),
    }


def observation_from_runtime_responses(
    *,
    dataset: EvaluationDataset,
    question_id: str,
    search_response: Mapping[str, object],
    answer_response: Mapping[str, object],
    authorized_anchor_ids: set[str],
    latency_ms: float,
    cost_usd: float,
) -> EvaluationObservation:
    """Normalize the public search and grounded-answer response shapes.

    The evaluator deliberately consumes JSON-shaped API responses rather than
    importing API classes. That keeps the benchmark executable from the worker
    package while binding it to the same citation fields exposed to clients.
    Only ``answered`` and ``partial`` answers may contribute accepted claims;
    every other answer state is measured as an abstention.
    """
    question = dataset.questions.get(question_id)
    if question is None:
        raise ValueError(f"Unknown evaluation question id: {question_id}")

    retrieved_anchor_ids, retrieved_source_ids = _search_sources(search_response)
    citation_anchor_ids, accepted_claims = _answer_claims(
        answer_response,
        question,
        retrieved_source_ids,
    )
    unauthorized = sorted(
        anchor_id
        for anchor_id, source_ids in retrieved_source_ids.items()
        if not any(
            _source_is_authorized(source_id, anchor_id, authorized_anchor_ids)
            for source_id in source_ids
        )
    )
    return {
        "question_id": question_id,
        "retrieved_anchor_ids": retrieved_anchor_ids,
        "citation_anchor_ids": citation_anchor_ids,
        "accepted_claims": accepted_claims,
        "unauthorized_retrieved_anchor_ids": unauthorized,
        "latency_ms": _non_negative_number(latency_ms, "runtime latency_ms"),
        "cost_usd": _non_negative_number(cost_usd, "runtime cost_usd"),
    }


def load_observations(path: Path, dataset_version: str) -> list[EvaluationObservation]:
    payload = _object(json.loads(path.read_text()), "results")
    if _string(payload.get("dataset_version"), "results dataset version") != dataset_version:
        raise ValueError("Results dataset_version does not match the evaluation dataset")
    return [_observation(item) for item in _list(payload.get("observations"), "observations")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and grounded-answer quality.")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    observations = load_observations(args.results, dataset.version)
    print(json.dumps(evaluate_retrieval_quality(dataset, observations), sort_keys=True))


def _observation(value: object) -> EvaluationObservation:
    item = _object(value, "observation")
    latency = _non_negative_number(item.get("latency_ms"), "observation latency_ms")
    return {
        "question_id": _string(item.get("question_id"), "observation question_id"),
        "retrieved_anchor_ids": _string_list(item.get("retrieved_anchor_ids"), "observation"),
        "citation_anchor_ids": _string_list(item.get("citation_anchor_ids"), "observation"),
        "accepted_claims": _claims(item.get("accepted_claims"), "observation"),
        "unauthorized_retrieved_anchor_ids": _string_list(
            item.get("unauthorized_retrieved_anchor_ids"), "observation"
        ),
        "latency_ms": float(latency),
        "cost_usd": _non_negative_number(item.get("cost_usd"), "observation cost_usd"),
    }


def _compare_baseline(metrics: EvaluationMetrics, baseline: Mapping[str, object]) -> BaselineResult:
    failures: list[str] = []
    for metric_name, threshold in baseline.items():
        threshold_value = _object(threshold, f"baseline {metric_name}")
        metric = metrics.get(metric_name)
        value = threshold_value.get("minimum")
        if value is not None and (
            not isinstance(value, int | float)
            or not isinstance(metric, int | float)
            or metric < value
        ):
            failures.append(f"{metric_name} is below its accepted minimum")
        value = threshold_value.get("maximum")
        if value is not None and (
            not isinstance(value, int | float)
            or not isinstance(metric, int | float)
            or metric > value
        ):
            failures.append(f"{metric_name} exceeds its accepted maximum")
        accepted_baseline = threshold_value.get("accepted_baseline")
        maximum_regression = threshold_value.get("maximum_regression")
        if (accepted_baseline is not None or maximum_regression is not None) and (
            not isinstance(accepted_baseline, int | float)
            or not isinstance(maximum_regression, int | float)
            or not isinstance(metric, int | float)
            or metric < accepted_baseline - maximum_regression
        ):
            failures.append(f"{metric_name} exceeds the allowed accepted-baseline regression")
    return {"passed": not failures, "failures": failures}


def _claims(value: object, label: str) -> list[AcceptedClaim]:
    claims: list[AcceptedClaim] = []
    for item in _list(value, f"{label} claims"):
        claim = _object(item, f"{label} claim")
        claims.append(
            {
                "claim_id": _string(claim.get("claim_id"), f"{label} claim id"),
                "citation_anchor_ids": _string_list(
                    claim.get("citation_anchor_ids"), f"{label} claim citations"
                ),
            }
        )
    return claims


def _search_sources(search_response: Mapping[str, object]) -> tuple[list[str], dict[str, set[str]]]:
    anchor_ids: list[str] = []
    source_ids: dict[str, set[str]] = {}
    for item in _list(search_response.get("items"), "search response items"):
        result = _object(item, "search response item")
        agreement_id = _string(result.get("agreement_id"), "search response agreement_id")
        citation = _object(result.get("citation"), "search response citation")
        for anchor_id in _string_list(citation.get("anchor_ids"), "search response anchors"):
            anchor_ids.append(anchor_id)
            source_ids.setdefault(anchor_id, set()).add(_source_id(agreement_id, anchor_id))
    return _ordered_unique(anchor_ids), source_ids


def _answer_claims(
    answer_response: Mapping[str, object],
    question: Mapping[str, object],
    retrieved_source_ids: Mapping[str, set[str]],
) -> tuple[list[str], list[AcceptedClaim]]:
    status = _string(answer_response.get("status"), "answer response status")
    if status not in {"answered", "partial"}:
        return [], []

    expected_claims = _claims(question.get("expected_claims"), "evaluation question")
    citation_anchor_ids: list[str] = []
    accepted_claims: list[AcceptedClaim] = []
    claims = _list(answer_response.get("claims"), "answer response claims")
    for index, item in enumerate(claims, start=1):
        claim = _object(item, "answer response claim")
        citations = _list(claim.get("citations"), "answer response citations")
        anchors: list[str] = []
        for citation in citations:
            payload = _object(citation, "answer response citation")
            anchor_id = _string(payload.get("anchor_id"), "citation anchor")
            agreement_id = _string(payload.get("agreement_id"), "citation agreement_id")
            if _source_id(agreement_id, anchor_id) in retrieved_source_ids.get(anchor_id, set()):
                anchors.append(anchor_id)
        anchors = _ordered_unique(anchors)
        citation_anchor_ids.extend(anchors)
        accepted_claims.append(
            {
                "claim_id": _expected_claim_id(expected_claims, anchors, index),
                "citation_anchor_ids": anchors,
            }
        )
    return _ordered_unique(citation_anchor_ids), accepted_claims


def _expected_claim_id(
    expected_claims: list[AcceptedClaim], citation_anchor_ids: list[str], index: int
) -> str:
    anchors = set(citation_anchor_ids)
    for claim in expected_claims:
        if anchors == set(claim["citation_anchor_ids"]):
            return claim["claim_id"]
    return f"runtime-claim-{index}"


def _source_id(agreement_id: str, anchor_id: str) -> str:
    """Keep identical anchors from different agreements distinguishable."""
    return f"{agreement_id}:{anchor_id}"


def _source_is_authorized(source_id: str, anchor_id: str, authorized_source_ids: set[str]) -> bool:
    """Accept source-scoped authorisation, with bare anchors for legacy fixtures."""
    return source_id in authorized_source_ids or anchor_id in authorized_source_ids


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


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


def _string_list(value: object, label: str) -> list[str]:
    return [_string(item, label) for item in _list(value, label)]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _p95(values: list[float]) -> float:
    return sorted(values)[ceil(0.95 * len(values)) - 1] if values else 0.0


def _non_negative_number(value: object, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return float(value)


if __name__ == "__main__":
    main()
