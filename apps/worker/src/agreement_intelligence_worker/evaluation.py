from __future__ import annotations

import json
from pathlib import Path
from typing import NotRequired, TypedDict

from agreement_intelligence_worker.analysis_provider import AnalysisProvider
from agreement_intelligence_worker.analysis_validation import (
    ProviderOutputValidationError,
    validate_provider_analysis,
)
from agreement_intelligence_worker.classification import classify_document


class GoldenCase(TypedDict):
    text: str
    expected_family: str


class EvaluationReport(TypedDict):
    cases: int
    classification_accuracy: float
    modes: set[str]
    hybrid_classification_accuracy: NotRequired[float]


def evaluate(
    cases: list[GoldenCase], *, provider: AnalysisProvider | None = None
) -> EvaluationReport:
    correct = sum(
        classify_document(case["text"]).family == case["expected_family"] for case in cases
    )
    count = len(cases)
    report: EvaluationReport = {
        "cases": count,
        "classification_accuracy": correct / count if count else 0.0,
        "modes": {"deterministic"},
    }
    if provider is None:
        return report

    hybrid_correct = 0
    for index, case in enumerate(cases):
        anchor_id = f"evaluation-{index}"
        try:
            analysis = validate_provider_analysis(
                provider.analyze([(anchor_id, case["text"])]), {anchor_id}
            )
        except (ProviderOutputValidationError, ValueError):
            continue
        hybrid_correct += analysis.classification["family"] == case["expected_family"]

    report["modes"] = {"deterministic", "hybrid"}
    report["hybrid_classification_accuracy"] = hybrid_correct / count if count else 0.0
    return report


def main() -> None:
    dataset = Path(__file__).parents[2] / "tests" / "golden" / "agreement-families.json"
    report = evaluate(json.loads(dataset.read_text()))
    print(json.dumps({**report, "modes": sorted(report["modes"])}, sort_keys=True))


if __name__ == "__main__":
    main()
