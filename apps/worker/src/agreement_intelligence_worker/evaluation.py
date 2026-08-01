from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from agreement_intelligence_worker.classification import classify_document


class GoldenCase(TypedDict):
    text: str
    expected_family: str


def evaluate(cases: list[GoldenCase]) -> dict[str, float | int]:
    correct = sum(
        classify_document(case["text"]).family == case["expected_family"] for case in cases
    )
    count = len(cases)
    return {"cases": count, "classification_accuracy": correct / count if count else 0.0}


def main() -> None:
    dataset = Path(__file__).parents[2] / "tests" / "golden" / "agreement-families.json"
    report = evaluate(json.loads(dataset.read_text()))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
