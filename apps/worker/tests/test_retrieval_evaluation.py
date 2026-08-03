from __future__ import annotations

import json
from pathlib import Path
from subprocess import run

from agreement_intelligence_worker.retrieval_evaluation import (
    EvaluationDataset,
    evaluate_retrieval_quality,
    observation_from_runtime_responses,
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


def test_runtime_response_adapter_preserves_real_search_and_grounded_answer_evidence() -> None:
    dataset = EvaluationDataset(
        version="1.0",
        questions={
            "termination-notice": {
                "expected_retrieval_anchor_ids": ["msa-termination"],
                "expected_citation_anchor_ids": ["msa-termination"],
                "expected_claims": [
                    {
                        "claim_id": "termination-notice",
                        "citation_anchor_ids": ["msa-termination"],
                    }
                ],
            }
        },
        baseline={},
    )

    observation = observation_from_runtime_responses(
        dataset=dataset,
        question_id="termination-notice",
        search_response={
            "items": [
                {
                    "agreement_id": "11111111-1111-1111-1111-111111111111",
                    "citation": {"anchor_ids": ["msa-termination"]},
                }
            ]
        },
        answer_response={
            "status": "answered",
            "claims": [
                {
                    "citations": [
                        {
                            "anchor_id": "msa-termination",
                            "agreement_id": "11111111-1111-1111-1111-111111111111",
                            "supporting_quote": "90 days",
                        }
                    ]
                }
            ],
        },
        authorized_anchor_ids={"11111111-1111-1111-1111-111111111111:msa-termination"},
        latency_ms=11,
        cost_usd=0.01,
    )

    assert observation == {
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
        "latency_ms": 11.0,
        "cost_usd": 0.01,
    }


def test_runtime_adapter_rejects_a_citation_from_a_different_agreement() -> None:
    dataset = EvaluationDataset(
        version="1.0",
        questions={
            "termination-notice": {
                "expected_retrieval_anchor_ids": ["msa-termination"],
                "expected_citation_anchor_ids": ["msa-termination"],
                "expected_claims": [
                    {
                        "claim_id": "termination-notice",
                        "citation_anchor_ids": ["msa-termination"],
                    }
                ],
            }
        },
        baseline={},
    )

    observation = observation_from_runtime_responses(
        dataset=dataset,
        question_id="termination-notice",
        search_response={
            "items": [
                {
                    "agreement_id": "11111111-1111-1111-1111-111111111111",
                    "citation": {"anchor_ids": ["msa-termination"]},
                }
            ]
        },
        answer_response={
            "status": "partial",
            "claims": [
                {
                    "citations": [
                        {
                            "anchor_id": "msa-termination",
                            "agreement_id": "22222222-2222-2222-2222-222222222222",
                            "supporting_quote": "90 days",
                        }
                    ]
                }
            ],
        },
        authorized_anchor_ids={"11111111-1111-1111-1111-111111111111:msa-termination"},
        latency_ms=11,
        cost_usd=0.01,
    )

    assert observation["citation_anchor_ids"] == []
    assert observation["accepted_claims"] == [
        {"claim_id": "runtime-claim-1", "citation_anchor_ids": []}
    ]
