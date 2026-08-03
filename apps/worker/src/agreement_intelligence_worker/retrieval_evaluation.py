from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import TypedDict, cast


class SourceReference(TypedDict):
    agreement_id: str
    anchor_id: str
    source_checksum: str
    source_version: str


class AcceptedClaim(TypedDict):
    claim_id: str
    citation_sources: list[SourceReference]


class EvaluationObservation(TypedDict):
    question_id: str
    answer_status: str
    retrieved_sources: list[SourceReference]
    citation_sources: list[SourceReference]
    accepted_claims: list[AcceptedClaim]
    unauthorized_retrieved_sources: list[SourceReference]
    latency_ms: float
    cost_usd: float


class EvaluationMetrics(TypedDict):
    retrieval_recall_at_5: float
    citation_precision: float
    citation_recall: float
    unsupported_accepted_claims: int
    unsupported_accepted_claim_rate: float
    unauthorized_retrieval_count: int
    forbidden_retrieval_count: int
    unexpected_outcome_count: int
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
_OUTCOMES = {
    "answer": {"answered", "partial"},
    "abstain": {"insufficient_evidence"},
    "needs_review": {"conflicting_evidence"},
    "reject": {"insufficient_evidence"},
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
        _expected_outcome(question, question_id)
        _sources(question.get("expected_retrieval_sources"), f"question {question_id} retrieval")
        _sources(question.get("expected_citation_sources"), f"question {question_id} citations")
        _sources(question.get("forbidden_sources", []), f"question {question_id} forbidden sources")
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
    observation_ids = [observation["question_id"] for observation in observations]
    duplicates = sorted(
        {question_id for question_id in observation_ids if observation_ids.count(question_id) > 1}
    )
    if duplicates:
        raise ValueError(f"Results contain duplicate question ids: {duplicates}")
    observations_by_id = {observation["question_id"]: observation for observation in observations}
    unexpected = set(observations_by_id) - set(dataset.questions)
    missing = set(dataset.questions) - set(observations_by_id)
    if unexpected or missing:
        raise ValueError(
            f"Results must include every dataset question; missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )

    retrieval_relevant = retrieval_found = citation_expected = citation_found = (
        citation_returned
    ) = 0
    unsupported_claims = accepted_claim_count = unauthorized_retrieval_count = 0
    forbidden_retrieval_count = unexpected_outcome_count = 0
    latencies: list[float] = []
    costs: list[float] = []
    for question_id, question in dataset.questions.items():
        observation = observations_by_id[question_id]
        expected_retrieval = _source_keys(
            _sources(question.get("expected_retrieval_sources"), question_id)
        )
        expected_citations = _source_keys(
            _sources(question.get("expected_citation_sources"), question_id)
        )
        forbidden_sources = _source_keys(
            _sources(question.get("forbidden_sources", []), question_id)
        )
        retrieved = _source_keys(observation["retrieved_sources"][:5])
        citations = _source_keys(observation["citation_sources"])
        retrieval_relevant += len(expected_retrieval)
        retrieval_found += len(expected_retrieval & retrieved)
        citation_expected += len(expected_citations)
        citation_found += len(expected_citations & citations)
        citation_returned += len(citations)
        forbidden_retrieval_count += len(
            forbidden_sources & _source_keys(observation["retrieved_sources"])
        )
        if observation["answer_status"] not in _OUTCOMES[_expected_outcome(question, question_id)]:
            unexpected_outcome_count += 1
        expected_claims = {
            claim["claim_id"]: _source_keys(claim["citation_sources"])
            for claim in _claims(question.get("expected_claims"), question_id)
        }
        for claim in observation["accepted_claims"]:
            accepted_claim_count += 1
            if not (
                _source_keys(claim["citation_sources"])
                & expected_claims.get(claim["claim_id"], set())
            ):
                unsupported_claims += 1
        unauthorized_retrieval_count += len(observation["unauthorized_retrieved_sources"])
        latencies.append(observation["latency_ms"])
        costs.append(observation["cost_usd"])

    metrics: EvaluationMetrics = {
        "retrieval_recall_at_5": _ratio(retrieval_found, retrieval_relevant),
        "citation_precision": _ratio(citation_found, citation_returned),
        "citation_recall": _ratio(citation_found, citation_expected),
        "unsupported_accepted_claims": unsupported_claims,
        "unsupported_accepted_claim_rate": (
            unsupported_claims / accepted_claim_count if accepted_claim_count else 0.0
        ),
        "unauthorized_retrieval_count": unauthorized_retrieval_count,
        "forbidden_retrieval_count": forbidden_retrieval_count,
        "unexpected_outcome_count": unexpected_outcome_count,
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
    authorized_source_ids: set[str],
    latency_ms: float,
    cost_usd: float,
) -> EvaluationObservation:
    """Normalize the public search response and QuestionTurnResponse shapes."""
    question = dataset.questions.get(question_id)
    if question is None:
        raise ValueError(f"Unknown evaluation question id: {question_id}")
    retrieved_sources = _search_sources(search_response)
    answer = _object(answer_response.get("answer", answer_response), "answer response")
    answer_status = _string(answer.get("status"), "answer response status")
    citation_sources, accepted_claims = _answer_claims(
        answer, question, _source_keys(retrieved_sources)
    )
    unauthorized = [
        source for source in retrieved_sources if _source_key(source) not in authorized_source_ids
    ]
    return {
        "question_id": question_id,
        "answer_status": answer_status,
        "retrieved_sources": retrieved_sources,
        "citation_sources": citation_sources,
        "accepted_claims": accepted_claims,
        "unauthorized_retrieved_sources": unauthorized,
        "latency_ms": _non_negative_number(latency_ms, "runtime latency_ms"),
        "cost_usd": _non_negative_number(cost_usd, "runtime cost_usd"),
    }


def load_observations(path: Path, dataset: EvaluationDataset) -> list[EvaluationObservation]:
    payload = _object(json.loads(path.read_text()), "results")
    if _string(payload.get("dataset_version"), "results dataset version") != dataset.version:
        raise ValueError("Results dataset_version does not match the evaluation dataset")
    observations = payload.get("observations")
    runtime_observations = payload.get("runtime_observations")
    if observations is not None and runtime_observations is not None:
        raise ValueError("Results must provide observations or runtime_observations, not both")
    if observations is not None:
        return [_observation(item) for item in _list(observations, "observations")]
    return [
        _runtime_observation(item, dataset)
        for item in _list(runtime_observations, "runtime observations")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and grounded-answer quality.")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    observations = load_observations(args.results, dataset)
    print(json.dumps(evaluate_retrieval_quality(dataset, observations), sort_keys=True))


def _observation(value: object) -> EvaluationObservation:
    item = _object(value, "observation")
    return {
        "question_id": _string(item.get("question_id"), "observation question_id"),
        "answer_status": _string(item.get("answer_status"), "observation answer_status"),
        "retrieved_sources": _sources(
            item.get("retrieved_sources"), "observation retrieved sources"
        ),
        "citation_sources": _sources(item.get("citation_sources"), "observation citation sources"),
        "accepted_claims": _claims(item.get("accepted_claims"), "observation"),
        "unauthorized_retrieved_sources": _sources(
            item.get("unauthorized_retrieved_sources"), "observation unauthorized retrieved sources"
        ),
        "latency_ms": _non_negative_number(item.get("latency_ms"), "observation latency_ms"),
        "cost_usd": _non_negative_number(item.get("cost_usd"), "observation cost_usd"),
    }


def _runtime_observation(value: object, dataset: EvaluationDataset) -> EvaluationObservation:
    item = _object(value, "runtime observation")
    return observation_from_runtime_responses(
        dataset=dataset,
        question_id=_string(item.get("question_id"), "runtime observation question id"),
        search_response=_object(item.get("search_response"), "runtime observation search response"),
        answer_response=_object(item.get("answer_response"), "runtime observation answer response"),
        authorized_source_ids=set(
            _string_list(
                item.get("authorized_source_ids"), "runtime observation authorized source ids"
            )
        ),
        latency_ms=_non_negative_number(item.get("latency_ms"), "runtime observation latency_ms"),
        cost_usd=_non_negative_number(item.get("cost_usd"), "runtime observation cost_usd"),
    )


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


def _answer_claims(
    answer: Mapping[str, object], question: Mapping[str, object], retrieved_source_ids: set[str]
) -> tuple[list[SourceReference], list[AcceptedClaim]]:
    if _string(answer.get("status"), "answer response status") not in {"answered", "partial"}:
        return [], []
    expected_claims = _claims(question.get("expected_claims"), "evaluation question")
    citation_sources: list[SourceReference] = []
    accepted_claims: list[AcceptedClaim] = []
    for index, item in enumerate(_list(answer.get("claims"), "answer response claims"), start=1):
        claim = _object(item, "answer response claim")
        sources = [
            source
            for source in _sources(claim.get("citations"), "answer response citations")
            if _source_key(source) in retrieved_source_ids
        ]
        sources = _ordered_unique_sources(sources)
        citation_sources.extend(sources)
        accepted_claims.append(
            {
                "claim_id": _expected_claim_id(expected_claims, sources, index),
                "citation_sources": sources,
            }
        )
    return _ordered_unique_sources(citation_sources), accepted_claims


def _expected_claim_id(
    expected_claims: list[AcceptedClaim], citation_sources: list[SourceReference], index: int
) -> str:
    sources = _source_keys(citation_sources)
    for claim in expected_claims:
        if sources == _source_keys(claim["citation_sources"]):
            return claim["claim_id"]
    return f"runtime-claim-{index}"


def _search_sources(search_response: Mapping[str, object]) -> list[SourceReference]:
    sources: list[SourceReference] = []
    for item in _list(search_response.get("items"), "search response items"):
        result = _object(item, "search response item")
        agreement_id = _string(result.get("agreement_id"), "search response agreement_id")
        citation = _object(result.get("citation"), "search response citation")
        checksum = _string(citation.get("source_checksum"), "search response source checksum")
        version = _string(citation.get("source_version"), "search response source version")
        for anchor_id in _string_list(citation.get("anchor_ids"), "search response anchors"):
            sources.append(
                {
                    "agreement_id": agreement_id,
                    "anchor_id": anchor_id,
                    "source_checksum": checksum,
                    "source_version": version,
                }
            )
    return _ordered_unique_sources(sources)


def _expected_outcome(question: Mapping[str, object], question_id: str) -> str:
    outcome = _string(question.get("expected_outcome"), f"question {question_id} expected outcome")
    if outcome not in _OUTCOMES:
        raise ValueError(f"question {question_id} has unsupported expected outcome: {outcome}")
    return outcome


def _claims(value: object, label: str) -> list[AcceptedClaim]:
    claims: list[AcceptedClaim] = []
    for item in _list(value, f"{label} claims"):
        claim = _object(item, f"{label} claim")
        claims.append(
            {
                "claim_id": _string(claim.get("claim_id"), f"{label} claim id"),
                "citation_sources": _sources(
                    claim.get("citation_sources"), f"{label} claim citations"
                ),
            }
        )
    return claims


def _sources(value: object, label: str) -> list[SourceReference]:
    sources: list[SourceReference] = []
    for item in _list(value, label):
        source = _object(item, f"{label} source")
        sources.append(
            {
                "agreement_id": _string(source.get("agreement_id"), f"{label} agreement id"),
                "anchor_id": _string(source.get("anchor_id"), f"{label} anchor id"),
                "source_checksum": _string(
                    source.get("source_checksum"), f"{label} source checksum"
                ),
                "source_version": _string(source.get("source_version"), f"{label} source version"),
            }
        )
    return sources


def _source_key(source: SourceReference) -> str:
    return "\x1f".join(
        (
            source["agreement_id"],
            source["source_checksum"],
            source["source_version"],
            source["anchor_id"],
        )
    )


def _source_keys(sources: Iterable[SourceReference]) -> set[str]:
    return {_source_key(source) for source in sources}


def _ordered_unique_sources(sources: Iterable[SourceReference]) -> list[SourceReference]:
    unique: dict[str, SourceReference] = {}
    for source in sources:
        unique.setdefault(_source_key(source), source)
    return list(unique.values())


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
