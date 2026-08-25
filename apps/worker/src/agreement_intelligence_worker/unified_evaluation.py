from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import TypedDict, cast
from uuid import UUID

from agreement_intelligence_worker.classification import classify_document
from agreement_intelligence_worker.clause_extraction import extract_clauses
from agreement_intelligence_worker.evaluation import GoldenCase, evaluate
from agreement_intelligence_worker.evidence_validation import (
    AnswerCandidate,
    Citation,
    EvidenceAnchor,
    EvidenceSnippet,
    GroundedClaim,
    GroundedQuestionRequest,
    answer_question,
)
from agreement_intelligence_worker.guardrails import validate_untrusted_evidence
from agreement_intelligence_worker.retrieval_evaluation import (
    AcceptedClaim,
    EvaluationObservation,
    SourceReference,
    evaluate_retrieval_quality,
)
from agreement_intelligence_worker.retrieval_evaluation import (
    load_dataset as load_retrieval_dataset,
)
from agreement_intelligence_worker.version_alignment import (
    CanonicalElement,
    CanonicalVersion,
    align_versions,
)
from agreement_intelligence_worker.version_comparison_evaluation import (
    AlignmentLabel,
    ComparisonObservation,
    ComparisonObservationChange,
    evaluate_version_comparisons,
)
from agreement_intelligence_worker.version_comparison_evaluation import (
    load_dataset as load_comparison_dataset,
)
from agreement_intelligence_worker.version_materiality import (
    MaterialityCandidate,
    assess_materiality,
)


class ChangedCase(TypedDict):
    id: str
    capability: str
    previous_fingerprint: str
    current_fingerprint: str
    summary: str


class UsageSummary(TypedDict):
    latency_ms_total: float
    tokens_total: int
    cost_usd_total: float


class CapabilityReport(TypedDict):
    cases: int
    metrics: dict[str, float]


class EvaluationReport(TypedDict):
    manifest_version: str
    passed: bool
    capabilities: dict[str, CapabilityReport]
    metrics: dict[str, float]
    deltas: dict[str, float]
    changed_cases: list[ChangedCase]
    usage: UsageSummary
    failures: list[str]


_GOLDEN_DIRECTORY = Path(__file__).parents[2] / "tests" / "golden" / "unified" / "v1"
_DEFAULT_MANIFEST = _GOLDEN_DIRECTORY / "manifest.json"
_DEFAULT_BASELINE = _GOLDEN_DIRECTORY / "accepted-baseline.json"
_REQUIRED_GATE_METRICS = {
    "comparison.critical_material_change_recall",
    "grounding.citation_precision",
    "grounding.unsupported_accepted_claims",
    "retrieval.recall_at_5",
    "retrieval.unauthorized_retrieval_count",
}
_COUNT_METRICS = {
    "grounding.unsupported_accepted_claims",
    "guardrails.unsafe_acceptances",
    "retrieval.unauthorized_retrieval_count",
}
_RATIO_METRICS = {
    "classification.accuracy",
    "comparison.critical_material_change_recall",
    "extraction.clause_f1",
    "grounding.citation_precision",
    "retrieval.recall_at_5",
}
_EVALUATION_ORGANIZATION_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "agreement",
    "applies",
    "are",
    "be",
    "by",
    "clause",
    "does",
    "every",
    "for",
    "from",
    "how",
    "is",
    "it",
    "much",
    "of",
    "on",
    "per",
    "previous",
    "required",
    "the",
    "this",
    "to",
    "what",
    "which",
    "without",
}


@dataclass(frozen=True)
class _RuntimeSource:
    agreement_id: UUID
    agreement_title: str
    anchor_id: str
    source_checksum: str
    source_version: str
    tenant_id: str
    workspace_id: str
    text: str


def evaluate_release(
    manifest_path: Path,
    baseline_path: Path,
    results_path: Path,
) -> EvaluationReport:
    if baseline_path.resolve() == results_path.resolve():
        raise ValueError("accepted baseline cannot be used as results")

    manifest = _object(_load_json(manifest_path), "manifest")
    baseline = _object(_load_json(baseline_path), "accepted baseline")
    results = _object(_load_json(results_path), "results")
    version = _string(manifest.get("version"), "manifest version")
    _verify_frozen_datasets(manifest, manifest_path)
    if _string(baseline.get("version"), "baseline version") != version:
        raise ValueError("accepted baseline version does not match manifest")
    if _string(results.get("version"), "results version") != version:
        raise ValueError("results version does not match manifest")

    required_capabilities = _unique_strings(
        manifest.get("required_capabilities"), "required capabilities"
    )
    cases = [_result_case(item) for item in _list(results.get("cases"), "results cases")]
    case_ids = [case["id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("results contain duplicate case ids")
    observed_capabilities = {case["capability"] for case in cases}
    missing_capabilities = sorted(set(required_capabilities) - observed_capabilities)
    unexpected_capabilities = sorted(observed_capabilities - set(required_capabilities))
    if missing_capabilities or unexpected_capabilities:
        raise ValueError(
            "results capabilities do not match manifest; "
            f"missing={missing_capabilities}, unexpected={unexpected_capabilities}"
        )

    capability_metrics: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    capability_case_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        capability = case["capability"]
        capability_case_counts[capability] += 1
        for metric_name, metric_value in case["metrics"].items():
            _validate_metric(f"{capability}.{metric_name}", metric_value)
            capability_metrics[capability][metric_name].append(metric_value)

    capabilities: dict[str, CapabilityReport] = {}
    metrics: dict[str, float] = {}
    for capability in required_capabilities:
        aggregated = {}
        for metric_name, values in sorted(capability_metrics[capability].items()):
            qualified_name = f"{capability}.{metric_name}"
            aggregated[metric_name] = (
                sum(values) if qualified_name in _COUNT_METRICS else fmean(values)
            )
        capabilities[capability] = {
            "cases": capability_case_counts[capability],
            "metrics": aggregated,
        }
        metrics.update(
            {f"{capability}.{metric_name}": value for metric_name, value in aggregated.items()}
        )

    baseline_metrics = _object(baseline.get("metrics"), "baseline metrics")
    missing_gate_metrics = sorted(_REQUIRED_GATE_METRICS - set(baseline_metrics))
    if missing_gate_metrics:
        raise ValueError(f"accepted baseline is missing required gates: {missing_gate_metrics}")
    unexpected_results = sorted(set(metrics) - set(baseline_metrics))
    missing_results = sorted(set(baseline_metrics) - set(metrics))
    if missing_results or unexpected_results:
        raise ValueError(
            "result metrics do not match accepted baseline; "
            f"missing={missing_results}, unexpected={unexpected_results}"
        )

    failures: list[str] = []
    deltas: dict[str, float] = {}
    for metric_name, threshold_value in baseline_metrics.items():
        threshold = _object(threshold_value, f"baseline metric {metric_name}")
        observed = metrics[metric_name]
        accepted = _number(threshold.get("accepted"), f"{metric_name} accepted")
        _validate_metric(metric_name, accepted)
        deltas[metric_name] = round(observed - accepted, 8)
        minimum = threshold.get("minimum")
        if minimum is not None:
            minimum_value = _number(minimum, f"{metric_name} minimum")
            _validate_metric(metric_name, minimum_value)
            if observed < minimum_value:
                failures.append(
                    f"{metric_name} is below its accepted minimum {minimum_value} "
                    f"(observed {observed})"
                )
        maximum = threshold.get("maximum")
        if maximum is not None:
            maximum_value = _number(maximum, f"{metric_name} maximum")
            _validate_metric(metric_name, maximum_value)
            if observed > maximum_value:
                failures.append(
                    f"{metric_name} exceeds its accepted maximum {maximum_value} "
                    f"(observed {observed})"
                )
        maximum_regression = threshold.get("maximum_regression")
        if maximum_regression is not None:
            regression_value = _non_negative_number(
                maximum_regression, f"{metric_name} maximum regression"
            )
            if observed < accepted - regression_value:
                failures.append(
                    f"{metric_name} regressed more than {regression_value} from {accepted} "
                    f"(observed {observed})"
                )

    baseline_fingerprints = _object(baseline.get("case_fingerprints"), "baseline case fingerprints")
    changed_cases: list[ChangedCase] = []
    for case in cases:
        identifier = case["id"]
        previous = _string(
            baseline_fingerprints.get(identifier), f"baseline fingerprint for {identifier}"
        )
        if previous != case["fingerprint"]:
            changed_cases.append(
                {
                    "id": identifier,
                    "capability": case["capability"],
                    "previous_fingerprint": previous,
                    "current_fingerprint": case["fingerprint"],
                    "summary": case["change_summary"] or "Evaluation case output changed.",
                }
            )
    unexpected_fingerprints = sorted(set(baseline_fingerprints) - set(case_ids))
    if unexpected_fingerprints:
        raise ValueError(
            f"accepted baseline contains cases missing from results: {unexpected_fingerprints}"
        )

    return {
        "manifest_version": version,
        "passed": not failures,
        "capabilities": capabilities,
        "metrics": metrics,
        "deltas": deltas,
        "changed_cases": changed_cases,
        "usage": {
            "latency_ms_total": round(sum(case["latency_ms"] for case in cases), 3),
            "tokens_total": sum(case["tokens"] for case in cases),
            "cost_usd_total": round(sum(case["cost_usd"] for case in cases), 8),
        },
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deterministic unified AI release gate.")
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--baseline", type=Path, default=_DEFAULT_BASELINE)
    parser.add_argument(
        "--results",
        type=Path,
        help="Explicit normalized results. Omit to execute the deterministic graders.",
    )
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--markdown-report", type=Path)
    args = parser.parse_args()
    results_path = args.results
    generated_results: Path | None = None
    if results_path is None:
        generated_results = _write_generated_results(
            args.manifest,
            args.json_report.parent if args.json_report else Path("artifacts/evaluation"),
        )
        results_path = generated_results
    report = evaluate_release(args.manifest, args.baseline, results_path)
    rendered_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_report is not None:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(rendered_json)
    if args.markdown_report is not None:
        args.markdown_report.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_report.write_text(_markdown(report))
    print(rendered_json, end="")
    if not report["passed"]:
        raise SystemExit(1)


def _write_generated_results(manifest_path: Path, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / "unified-runtime-results.json"
    payload = run_deterministic_graders(manifest_path)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return output_path


def run_deterministic_graders(manifest_path: Path = _DEFAULT_MANIFEST) -> dict[str, object]:
    manifest = _object(_load_json(manifest_path), "manifest")
    version = _string(manifest.get("version"), "manifest version")
    _verify_frozen_datasets(manifest, manifest_path)
    datasets = _object(manifest.get("datasets"), "manifest datasets")

    classification_path = _dataset_path(datasets, "classification", manifest_path)
    classification_cases = cast(list[GoldenCase], _load_json(classification_path))
    classification_report = evaluate(classification_cases)
    classification_output = [
        {
            "expected": case["expected_family"],
            "observed": _classification(case["text"]),
        }
        for case in classification_cases
    ]

    extraction_config = _object(datasets.get("extraction"), "manifest dataset extraction")
    extraction_path = _dataset_path(datasets, "extraction", manifest_path)
    blocks = _anchored_blocks(extraction_path.read_text())
    clauses = extract_clauses(blocks)
    expected_categories = set(
        _unique_strings(extraction_config.get("expected_categories"), "expected clause categories")
    )
    observed_categories = {clause["category"] for clause in clauses}
    clause_precision = _ratio(
        len(expected_categories & observed_categories), len(observed_categories)
    )
    clause_recall = _ratio(len(expected_categories & observed_categories), len(expected_categories))
    clause_f1 = _f1(clause_precision, clause_recall)

    retrieval_path = _dataset_path(datasets, "retrieval", manifest_path)
    retrieval_dataset = load_retrieval_dataset(retrieval_path)
    retrieval_observations = _retrieval_observations(
        retrieval_dataset.questions,
        _runtime_sources(retrieval_path),
    )
    retrieval_report = evaluate_retrieval_quality(retrieval_dataset, retrieval_observations)

    comparison_path = _dataset_path(datasets, "comparison", manifest_path)
    comparison_dataset = load_comparison_dataset(comparison_path)
    comparison_observations = _comparison_observations(comparison_dataset.cases)
    comparison_report = evaluate_version_comparisons(comparison_dataset, comparison_observations)

    guardrail_path = _dataset_path(datasets, "guardrails", manifest_path)
    guardrail_payload = _object(_load_json(guardrail_path), "guardrail dataset")
    guardrail_outputs = []
    unsafe_acceptances = 0
    for raw_case in _list(guardrail_payload.get("cases"), "guardrail cases"):
        case = _object(raw_case, "guardrail case")
        evidence = [
            (_string(pair[0], "guardrail anchor"), _string(pair[1], "guardrail text"))
            for raw_pair in _list(case.get("evidence"), "guardrail evidence")
            if len(pair := _list(raw_pair, "guardrail evidence pair")) == 2
        ]
        allowed = _unique_strings(case.get("allowed_anchor_ids"), "allowed anchor ids")
        decision = validate_untrusted_evidence(evidence, allowed)
        expected_status = _string(case.get("status"), "guardrail expected status")
        if expected_status in {"block", "review"} and decision.status == "allow":
            unsafe_acceptances += 1
        guardrail_outputs.append(
            {
                "name": _string(case.get("name"), "guardrail case name"),
                "expected_status": expected_status,
                "status": decision.status,
                "reason_codes": list(decision.reason_codes),
            }
        )

    retrieval_metrics = retrieval_report["metrics"]
    comparison_metrics = comparison_report["metrics"]
    return {
        "version": version,
        "cases": [
            _generated_case(
                "classification-family",
                "classification",
                classification_output,
                {"accuracy": classification_report["classification_accuracy"]},
            ),
            _generated_case(
                "comparison-materiality",
                "comparison",
                {
                    "observations": comparison_observations,
                    "metrics": comparison_metrics,
                },
                {
                    "critical_material_change_recall": comparison_metrics[
                        "critical_material_change_recall"
                    ]
                },
            ),
            _generated_case(
                "extraction-clauses",
                "extraction",
                clauses,
                {"clause_f1": clause_f1},
            ),
            _generated_case(
                "grounding-citations",
                "grounding",
                {
                    "observations": retrieval_observations,
                    "metrics": retrieval_metrics,
                },
                {
                    "citation_precision": retrieval_metrics["citation_precision"],
                    "unsupported_accepted_claims": retrieval_metrics["unsupported_accepted_claims"],
                },
            ),
            _generated_case(
                "guardrails-injection",
                "guardrails",
                guardrail_outputs,
                {"unsafe_acceptances": unsafe_acceptances},
            ),
            _generated_case(
                "retrieval-portfolio",
                "retrieval",
                {
                    "observations": retrieval_observations,
                    "metrics": retrieval_metrics,
                },
                {
                    "recall_at_5": retrieval_metrics["retrieval_recall_at_5"],
                    "unauthorized_retrieval_count": retrieval_metrics[
                        "unauthorized_retrieval_count"
                    ],
                },
            ),
        ],
    }


class _ResultCase(TypedDict):
    id: str
    capability: str
    fingerprint: str
    metrics: dict[str, float]
    change_summary: str
    latency_ms: float
    tokens: int
    cost_usd: float


def _generated_case(
    identifier: str,
    capability: str,
    normalized_output: object,
    metrics: Mapping[str, int | float],
) -> dict[str, object]:
    rendered = json.dumps(normalized_output, sort_keys=True, separators=(",", ":"))
    return {
        "id": identifier,
        "capability": capability,
        "fingerprint": hashlib.sha256(rendered.encode()).hexdigest(),
        "metrics": dict(metrics),
        "latency_ms": 0,
        "tokens": 0,
        "cost_usd": 0,
    }


def _classification(text: str) -> str:
    return classify_document(text).family


def _dataset_path(datasets: Mapping[str, object], capability: str, manifest_path: Path) -> Path:
    dataset = _object(datasets.get(capability), f"manifest dataset {capability}")
    relative_path = Path(_string(dataset.get("path"), f"{capability} dataset path"))
    if relative_path.is_absolute():
        raise ValueError(f"{capability} dataset path must be relative")
    return (manifest_path.parent / relative_path).resolve()


def _anchored_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^\[([^\]]+)]\s*(.+)$", stripped)
        if match:
            blocks.append((match.group(1), match.group(2)))
        else:
            blocks.append((f"block-{index}", stripped))
    return blocks


def _runtime_sources(dataset_path: Path) -> tuple[_RuntimeSource, ...]:
    payload = _object(_load_json(dataset_path), "retrieval dataset")
    fixture_cache: dict[Path, dict[str, str]] = {}
    sources: list[_RuntimeSource] = []
    for raw_source in _list(payload.get("runtime_sources"), "runtime sources"):
        source = _object(raw_source, "runtime source")
        fixture_path = dataset_path.parent / _string(
            source.get("fixture"), "runtime source fixture"
        )
        anchors = fixture_cache.setdefault(
            fixture_path,
            dict(_anchored_blocks(fixture_path.read_text())),
        )
        anchor_id = _string(source.get("anchor_id"), "runtime source anchor")
        if anchor_id not in anchors:
            raise ValueError(f"runtime source anchor is missing from fixture: {anchor_id}")
        tenant_id = _string(source.get("tenant_id"), "runtime source tenant")
        workspace_id = _string(source.get("workspace_id"), "runtime source workspace")
        sources.append(
            _RuntimeSource(
                agreement_id=UUID(
                    _string(source.get("agreement_id"), "runtime source agreement id")
                ),
                agreement_title=_string(
                    source.get("agreement_title"), "runtime source agreement title"
                ),
                anchor_id=anchor_id,
                source_checksum=_string(source.get("source_checksum"), "runtime source checksum"),
                source_version=_string(source.get("source_version"), "runtime source version"),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                text=anchors[anchor_id],
            )
        )
    if not sources:
        raise ValueError("retrieval dataset must include runtime sources")
    return tuple(sources)


def _search_terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in _SEARCH_STOP_WORDS
    }


def _source_reference(source: _RuntimeSource) -> SourceReference:
    return {
        "agreement_id": str(source.agreement_id),
        "anchor_id": source.anchor_id,
        "source_checksum": source.source_checksum,
        "source_version": source.source_version,
    }


def _deterministic_extractive_answerer(request: GroundedQuestionRequest) -> AnswerCandidate:
    question_terms = _search_terms(request.question)
    return AnswerCandidate(
        claims=tuple(
            GroundedClaim(
                text=snippet.text,
                citations=(
                    Citation(
                        anchor_id=snippet.anchor.anchor_id,
                        supporting_quote=snippet.text,
                    ),
                ),
            )
            for snippet in request.evidence
            if question_terms & _search_terms(snippet.text)
        )
    )


def _runtime_version(value: object, label: str) -> CanonicalVersion:
    version = _object(value, f"comparison {label}")
    checksum = _string(version.get("checksum"), f"comparison {label} checksum")
    elements: list[CanonicalElement] = []
    for raw_element in _list(version.get("elements"), f"comparison {label} elements"):
        element = _object(raw_element, f"comparison {label} element")
        element_id = _string(element.get("id"), f"comparison {label} element id")
        ordinal = element.get("ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise ValueError(f"comparison {label} element ordinal must be non-negative")
        citation_ids = tuple(
            _unique_strings(
                element.get("citation_ids"),
                f"comparison {label} element citation ids",
            )
        )
        elements.append(
            CanonicalElement(
                element_id=element_id,
                ordinal=ordinal,
                heading_path=(
                    _string(element.get("heading"), f"comparison {label} element heading"),
                ),
                clause_type=_string(
                    element.get("clause_type"), f"comparison {label} element clause type"
                ),
                text=_string(element.get("text"), f"comparison {label} element text"),
                citation_anchor_ids=citation_ids,
            )
        )
    return CanonicalVersion(checksum, tuple(elements))


def _retrieval_observations(
    questions: Mapping[str, Mapping[str, object]],
    sources: tuple[_RuntimeSource, ...],
) -> list[EvaluationObservation]:
    source_by_anchor = {source.anchor_id: source for source in sources}
    observations: list[EvaluationObservation] = []
    for question_id, question in questions.items():
        question_text = _string(question.get("question"), f"question {question_id}")
        principal = _object(question.get("principal"), f"question {question_id} principal")
        tenant_id = _string(principal.get("tenant_id"), f"question {question_id} tenant")
        workspace_id = _string(principal.get("workspace_id"), f"question {question_id} workspace")
        query_terms = _search_terms(question_text)
        ranked = sorted(
            (
                (len(query_terms & _search_terms(source.text)), source)
                for source in sources
                if source.tenant_id == tenant_id and source.workspace_id == workspace_id
            ),
            key=lambda item: (-item[0], item[1].anchor_id),
        )
        retrieved_sources = tuple(source for score, source in ranked[:5] if score)
        retrieved = [_source_reference(source) for source in retrieved_sources]
        conflict_ids = (
            tuple(source.anchor_id for source in retrieved_sources)
            if "liability" in question_text.casefold() and len(retrieved_sources) > 1
            else ()
        )
        evidence = tuple(
            EvidenceSnippet(
                anchor=EvidenceAnchor(
                    anchor_id=source.anchor_id,
                    source_checksum=source.source_checksum,
                    page_number=1,
                    start_offset=0,
                    end_offset=len(source.text),
                    conflicts_with=tuple(
                        anchor_id for anchor_id in conflict_ids if anchor_id != source.anchor_id
                    ),
                ),
                text=source.text,
            )
            for source in retrieved_sources
        )
        answer = answer_question(
            question=question_text,
            authorized_evidence=evidence,
            answerer=_deterministic_extractive_answerer,
            organization_id=_EVALUATION_ORGANIZATION_ID,
            workspace_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        )
        cited = [
            _source_reference(source_by_anchor[citation.anchor_id])
            for claim in answer.claims
            for citation in claim.citations
        ]
        accepted_claims = [
            {
                "claim_id": question_id,
                "citation_sources": [
                    _source_reference(source_by_anchor[citation.anchor_id])
                    for citation in claim.citations
                ],
            }
            for claim in answer.claims
        ]
        observations.append(
            {
                "question_id": question_id,
                "answer_status": answer.status,
                "retrieved_sources": retrieved,
                "citation_sources": cited,
                "accepted_claims": cast(list[AcceptedClaim], accepted_claims),
                "unauthorized_retrieved_sources": [
                    reference
                    for reference in retrieved
                    if (
                        source_by_anchor[reference["anchor_id"]].tenant_id != tenant_id
                        or source_by_anchor[reference["anchor_id"]].workspace_id != workspace_id
                    )
                ],
                "latency_ms": 0,
                "cost_usd": 0,
            }
        )
    return observations


def _comparison_observations(
    cases: Mapping[str, Mapping[str, object]],
) -> list[ComparisonObservation]:
    observations: list[ComparisonObservation] = []
    for case_id, case in cases.items():
        baseline = _runtime_version(case.get("baseline"), "baseline")
        target = _runtime_version(case.get("target"), "target")
        baseline_by_id = {element.element_id: element for element in baseline.elements}
        target_by_id = {element.element_id: element for element in target.elements}
        alignments: list[dict[str, object]] = []
        changes: list[dict[str, object]] = []
        for alignment in align_versions(baseline, target):
            alignment_elements = [
                *(baseline_by_id[element_id] for element_id in alignment.baseline_element_ids),
                *(target_by_id[element_id] for element_id in alignment.target_element_ids),
            ]
            clause_types = {
                element.clause_type for element in alignment_elements if element.clause_type
            }
            alignment_id = (
                next(iter(clause_types))
                if len(clause_types) == 1
                else (
                    "+".join(sorted(clause_types))
                    or "+".join(element.element_id for element in alignment_elements)
                )
            )
            baseline_text = "\n".join(
                baseline_by_id[element_id].text for element_id in alignment.baseline_element_ids
            )
            target_text = "\n".join(
                target_by_id[element_id].text for element_id in alignment.target_element_ids
            )
            baseline_citations = tuple(
                citation
                for element_id in alignment.baseline_element_ids
                for citation in baseline_by_id[element_id].citation_anchor_ids
            )
            target_citations = tuple(
                citation
                for element_id in alignment.target_element_ids
                for citation in target_by_id[element_id].citation_anchor_ids
            )
            change_type = "modified" if alignment.kind == "matched" else alignment.kind
            materiality = assess_materiality(
                MaterialityCandidate(
                    change_type=change_type,
                    baseline_text=baseline_text,
                    target_text=target_text,
                    baseline_citation_ids=baseline_citations,
                    target_citation_ids=target_citations,
                    alignment_confidence=alignment.confidence,
                    review_required=alignment.review_required,
                )
            )
            alignments.append(
                {
                    "id": alignment_id,
                    "kind": alignment.kind,
                    "review_required": alignment.review_required,
                }
            )
            changes.append(
                {
                    "id": alignment_id,
                    "change_type": change_type,
                    "severity": materiality.severity,
                    "citation_ids": [*baseline_citations, *target_citations],
                    "accepted": True,
                }
            )
        observations.append(
            {
                "case_id": case_id,
                "alignments": cast(list[AlignmentLabel], alignments),
                "changes": cast(list[ComparisonObservationChange], changes),
                "unauthorized_evidence_ids": [],
            }
        )
    return observations


def _result_case(value: object) -> _ResultCase:
    item = _object(value, "result case")
    metrics = {
        _string(name, "result metric name"): _number(metric, f"result metric {name}")
        for name, metric in _object(item.get("metrics"), "result case metrics").items()
    }
    if not metrics:
        raise ValueError("result case metrics cannot be empty")
    tokens = item.get("tokens")
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        raise ValueError("result case tokens must be a non-negative integer")
    summary = item.get("change_summary", "")
    if not isinstance(summary, str):
        raise ValueError("result case change_summary must be a string")
    return {
        "id": _string(item.get("id"), "result case id"),
        "capability": _string(item.get("capability"), "result case capability"),
        "fingerprint": _string(item.get("fingerprint"), "result case fingerprint"),
        "metrics": metrics,
        "change_summary": summary,
        "latency_ms": _non_negative_number(item.get("latency_ms"), "result case latency_ms"),
        "tokens": tokens,
        "cost_usd": _non_negative_number(item.get("cost_usd"), "result case cost_usd"),
    }


def _markdown(report: EvaluationReport) -> str:
    lines = [
        "# Unified AI quality report",
        "",
        f"- Gate: **{'PASS' if report['passed'] else 'FAIL'}**",
        f"- Manifest: `{report['manifest_version']}`",
        f"- Cost: `${report['usage']['cost_usd_total']:.8f}`",
        f"- Tokens: `{report['usage']['tokens_total']}`",
        f"- Latency total: `{report['usage']['latency_ms_total']:.3f} ms`",
        "",
        "## Metrics",
        "",
        "| Metric | Observed | Delta from accepted |",
        "| --- | ---: | ---: |",
    ]
    lines.extend(
        f"| `{name}` | {value:.8g} | {report['deltas'][name]:+.8g} |"
        for name, value in sorted(report["metrics"].items())
    )
    lines.extend(["", "## Changed cases", ""])
    if report["changed_cases"]:
        lines.extend(
            f"- `{case['id']}` ({case['capability']}): {case['summary']}"
            for case in report["changed_cases"]
        )
    else:
        lines.append("No case fingerprints changed.")
    lines.extend(["", "## Gate failures", ""])
    if report["failures"]:
        lines.extend(f"- {failure}" for failure in report["failures"])
    else:
        lines.append("No gate failures.")
    return "\n".join(lines) + "\n"


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load evaluation input {path}") from error


def _verify_frozen_datasets(manifest: Mapping[str, object], manifest_path: Path) -> None:
    configured = manifest.get("datasets")
    if configured is None:
        return
    datasets = _object(configured, "manifest datasets")
    if not datasets:
        raise ValueError("manifest datasets cannot be empty")
    for capability, raw_dataset in datasets.items():
        dataset = _object(raw_dataset, f"manifest dataset {capability}")
        relative_path = Path(_string(dataset.get("path"), f"{capability} dataset path"))
        if relative_path.is_absolute():
            raise ValueError(f"{capability} dataset path must be relative")
        dataset_path = (manifest_path.parent / relative_path).resolve()
        expected = _string(dataset.get("sha256"), f"{capability} dataset sha256")
        try:
            observed = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        except OSError as error:
            raise ValueError(f"cannot load frozen dataset {dataset_path}") from error
        if observed != expected:
            raise ValueError(
                f"frozen dataset checksum mismatch for {capability}: "
                f"expected {expected}, observed {observed}"
            )


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


def _unique_strings(value: object, label: str) -> list[str]:
    values = [_string(item, label) for item in _list(value, label)]
    if not values or len(values) != len(set(values)):
        raise ValueError(f"{label} must contain unique values")
    return values


def _number(value: object, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _non_negative_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise ValueError(f"{label} must be non-negative")
    return number


def _validate_metric(name: str, value: float) -> None:
    if name in _RATIO_METRICS and not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    if name in _COUNT_METRICS and (value < 0 or not value.is_integer()):
        raise ValueError(f"{name} must be a non-negative integer")


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


if __name__ == "__main__":
    main()
