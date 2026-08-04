from __future__ import annotations

import json
from pathlib import Path
from subprocess import run

from agreement_intelligence_worker.version_comparison_evaluation import (
    ComparisonEvaluationDataset,
    evaluate_version_comparisons,
    load_dataset,
)


def test_evaluation_reports_alignment_change_materiality_and_citation_metrics() -> None:
    dataset = ComparisonEvaluationDataset(
        version="1.0",
        cases={
            "liability-cap": {
                "expected_alignments": [
                    {
                        "id": "liability",
                        "kind": "matched",
                        "review_required": False,
                    }
                ],
                "expected_changes": [
                    {
                        "id": "liability-cap",
                        "change_type": "modified",
                        "severity": "critical",
                        "citation_ids": ["v1-liability", "v2-liability"],
                    }
                ],
            }
        },
        baseline={
            "alignment_f1": {"minimum": 0.8},
            "deterministic_change_accuracy": {"minimum": 0.85},
            "critical_material_change_recall": {"minimum": 1.0},
            "citation_precision": {"minimum": 1.0},
            "unsupported_accepted_claims": {"maximum": 0},
            "unauthorized_evidence_count": {"maximum": 0},
        },
    )

    report = evaluate_version_comparisons(
        dataset,
        [
            {
                "case_id": "liability-cap",
                "alignments": [
                    {
                        "id": "liability",
                        "kind": "matched",
                        "review_required": False,
                    }
                ],
                "changes": [
                    {
                        "id": "liability-cap",
                        "change_type": "modified",
                        "severity": "critical",
                        "citation_ids": ["v1-liability", "v2-liability"],
                        "accepted": True,
                    }
                ],
                "unauthorized_evidence_ids": [],
            }
        ],
    )

    assert report["metrics"] == {
        "alignment_f1": 1.0,
        "alignment_precision": 1.0,
        "alignment_recall": 1.0,
        "citation_precision": 1.0,
        "critical_material_change_recall": 1.0,
        "deterministic_change_accuracy": 1.0,
        "unauthorized_evidence_count": 0,
        "unsupported_accepted_claims": 0,
    }
    assert report["baseline"] == {"passed": True, "failures": []}


def test_evaluation_rejects_unsupported_claims_and_missed_critical_changes() -> None:
    dataset = ComparisonEvaluationDataset(
        version="1.0",
        cases={
            "termination": {
                "expected_alignments": [],
                "expected_changes": [
                    {
                        "id": "termination-notice",
                        "change_type": "modified",
                        "severity": "critical",
                        "citation_ids": ["v1-termination", "v2-termination"],
                    }
                ],
            }
        },
        baseline={
            "critical_material_change_recall": {"minimum": 1.0},
            "unsupported_accepted_claims": {"maximum": 0},
            "unauthorized_evidence_count": {"maximum": 0},
        },
    )

    report = evaluate_version_comparisons(
        dataset,
        [
            {
                "case_id": "termination",
                "alignments": [],
                "changes": [
                    {
                        "id": "unrelated",
                        "change_type": "added",
                        "severity": "low",
                        "citation_ids": ["unrelated-anchor"],
                        "accepted": True,
                    }
                ],
                "unauthorized_evidence_ids": ["forbidden-anchor"],
            }
        ],
    )

    assert report["metrics"]["critical_material_change_recall"] == 0.0
    assert report["metrics"]["unsupported_accepted_claims"] == 1
    assert report["metrics"]["unauthorized_evidence_count"] == 1
    assert report["baseline"]["passed"] is False


def test_version_comparison_evaluation_command_emits_the_frozen_baseline_report(
    tmp_path: Path,
) -> None:
    dataset = load_dataset()
    results_path = tmp_path / "results.json"
    observations = []
    for case_id, case in dataset.cases.items():
        expected_changes = case["expected_changes"]
        assert isinstance(expected_changes, list)
        observations.append(
            {
                "case_id": case_id,
                "alignments": case["expected_alignments"],
                "changes": [{**change, "accepted": True} for change in expected_changes],
                "unauthorized_evidence_ids": [],
            }
        )
    results_path.write_text(
        json.dumps({"dataset_version": dataset.version, "observations": observations})
    )

    result = run(
        [
            "make",
            "--no-print-directory",
            "version-comparison-eval",
            f"VERSION_COMPARISON_EVAL_RESULTS={results_path}",
        ],
        cwd=Path(__file__).parents[3],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert report["cases"] == 6
    assert report["baseline"] == {"passed": True, "failures": []}
