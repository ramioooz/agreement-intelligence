from __future__ import annotations

import json
from pathlib import Path
from subprocess import run

from agreement_intelligence_worker.retrieval_evaluation import (
    EvaluationDataset,
    evaluate_retrieval_quality,
)


def test_retrieval_evaluation_command_emits_a_versioned_baseline_report(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "results.json"
    results_path.write_text(
        json.dumps(
            {
                "dataset_version": "1.0",
                "observations": [
                    {
                        "question_id": "termination-notice",
                        "retrieved_anchor_ids": ["msa-termination"],
                        "citation_anchor_ids": ["msa-termination"],
                        "accepted_claims": [
                            {
                                "claim_id": "termination-notice",
                                "citation_anchor_ids": ["msa-termination"],
                            }
                        ],
                        "unauthorized_retrieved_anchor_ids": [],
                        "latency_ms": 12,
                        "cost_usd": 0.01,
                    },
                    {
                        "question_id": "governing-law-absent",
                        "retrieved_anchor_ids": [],
                        "citation_anchor_ids": [],
                        "accepted_claims": [],
                        "unauthorized_retrieved_anchor_ids": [],
                        "latency_ms": 8,
                        "cost_usd": 0.0,
                    },
                    {
                        "question_id": "liability-conflict",
                        "retrieved_anchor_ids": ["msa-liability", "side-letter-liability"],
                        "citation_anchor_ids": ["msa-liability", "side-letter-liability"],
                        "accepted_claims": [
                            {
                                "claim_id": "liability-conflict",
                                "citation_anchor_ids": [
                                    "msa-liability",
                                    "side-letter-liability",
                                ],
                            }
                        ],
                        "unauthorized_retrieved_anchor_ids": [],
                        "latency_ms": 21,
                        "cost_usd": 0.02,
                    },
                    {
                        "question_id": "ignore-instructions",
                        "retrieved_anchor_ids": [],
                        "citation_anchor_ids": [],
                        "accepted_claims": [],
                        "unauthorized_retrieved_anchor_ids": [],
                        "latency_ms": 5,
                        "cost_usd": 0.0,
                    },
                    {
                        "question_id": "board-only-pricing",
                        "retrieved_anchor_ids": [],
                        "citation_anchor_ids": [],
                        "accepted_claims": [],
                        "unauthorized_retrieved_anchor_ids": [],
                        "latency_ms": 5,
                        "cost_usd": 0.0,
                    },
                ],
            }
        )
    )

    result = run(
        [
            "uv",
            "run",
            "--package",
            "agreement-intelligence-worker",
            "python",
            "-m",
            "agreement_intelligence_worker.retrieval_evaluation",
            "--results",
            str(results_path),
        ],
        cwd=Path(__file__).parents[3],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["dataset_version"] == "1.0"
    assert report["metrics"] == {
        "citation_precision": 1.0,
        "citation_recall": 1.0,
        "cost_usd_total": 0.03,
        "latency_ms_p95": 21.0,
        "retrieval_recall_at_5": 1.0,
        "unauthorized_retrieval_count": 0,
        "unsupported_accepted_claims": 0,
        "unsupported_accepted_claim_rate": 0.0,
    }
    assert report["baseline"]["passed"] is True


def test_retrieval_evaluation_fails_when_recall_exceeds_the_allowed_baseline_regression() -> None:
    report = evaluate_retrieval_quality(
        EvaluationDataset(
            version="1.0",
            questions={
                "termination-notice": {
                    "expected_retrieval_anchor_ids": ["msa-termination"],
                    "expected_citation_anchor_ids": [],
                    "expected_claims": [],
                }
            },
            baseline={
                "retrieval_recall_at_5": {
                    "accepted_baseline": 0.8,
                    "maximum_regression": 0.05,
                }
            },
        ),
        [
            {
                "question_id": "termination-notice",
                "retrieved_anchor_ids": [],
                "citation_anchor_ids": [],
                "accepted_claims": [],
                "unauthorized_retrieved_anchor_ids": [],
                "latency_ms": 4.0,
                "cost_usd": 0.0,
            }
        ],
    )

    assert report["baseline"] == {
        "passed": False,
        "failures": ["retrieval_recall_at_5 exceeds the allowed accepted-baseline regression"],
    }
