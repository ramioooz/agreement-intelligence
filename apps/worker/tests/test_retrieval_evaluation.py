from __future__ import annotations

import json
from pathlib import Path
from subprocess import run
from typing import cast

from agreement_intelligence_worker.retrieval_evaluation import (
    AcceptedClaim,
    EvaluationDataset,
    EvaluationObservation,
    SourceReference,
    evaluate_retrieval_quality,
    load_observations,
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
                        "answer_status": "answered",
                        "retrieved_sources": [
                            _source(
                                "11111111-1111-1111-1111-111111111111", "msa-termination", "msa-v1"
                            )
                        ],
                        "citation_sources": [
                            _source(
                                "11111111-1111-1111-1111-111111111111", "msa-termination", "msa-v1"
                            )
                        ],
                        "accepted_claims": [
                            {
                                "claim_id": "termination-notice",
                                "citation_sources": [
                                    _source(
                                        "11111111-1111-1111-1111-111111111111",
                                        "msa-termination",
                                        "msa-v1",
                                    )
                                ],
                            }
                        ],
                        "unauthorized_retrieved_sources": [],
                        "latency_ms": 12,
                        "cost_usd": 0.01,
                    },
                    {
                        "question_id": "governing-law-absent",
                        "answer_status": "insufficient_evidence",
                        "retrieved_sources": [],
                        "citation_sources": [],
                        "accepted_claims": [],
                        "unauthorized_retrieved_sources": [],
                        "latency_ms": 8,
                        "cost_usd": 0.0,
                    },
                    {
                        "question_id": "liability-conflict",
                        "answer_status": "conflicting_evidence",
                        "retrieved_sources": [
                            _source(
                                "11111111-1111-1111-1111-111111111111", "msa-liability", "msa-v1"
                            ),
                            _source(
                                "22222222-2222-2222-2222-222222222222",
                                "side-letter-liability",
                                "side-letter-v1",
                            ),
                        ],
                        "citation_sources": [
                            _source(
                                "11111111-1111-1111-1111-111111111111", "msa-liability", "msa-v1"
                            ),
                            _source(
                                "22222222-2222-2222-2222-222222222222",
                                "side-letter-liability",
                                "side-letter-v1",
                            ),
                        ],
                        "accepted_claims": [
                            {
                                "claim_id": "liability-conflict",
                                "citation_sources": [
                                    _source(
                                        "11111111-1111-1111-1111-111111111111",
                                        "msa-liability",
                                        "msa-v1",
                                    ),
                                    _source(
                                        "22222222-2222-2222-2222-222222222222",
                                        "side-letter-liability",
                                        "side-letter-v1",
                                    ),
                                ],
                            }
                        ],
                        "unauthorized_retrieved_sources": [],
                        "latency_ms": 21,
                        "cost_usd": 0.02,
                    },
                    {
                        "question_id": "ignore-instructions",
                        "answer_status": "insufficient_evidence",
                        "retrieved_sources": [],
                        "citation_sources": [],
                        "accepted_claims": [],
                        "unauthorized_retrieved_sources": [],
                        "latency_ms": 5,
                        "cost_usd": 0.0,
                    },
                    {
                        "question_id": "board-only-pricing",
                        "answer_status": "insufficient_evidence",
                        "retrieved_sources": [],
                        "citation_sources": [],
                        "accepted_claims": [],
                        "unauthorized_retrieved_sources": [],
                        "latency_ms": 5,
                        "cost_usd": 0.0,
                    },
                ],
            }
        )
    )

    result = run(
        [
            "make",
            "retrieval-eval",
            f"RETRIEVAL_EVAL_RESULTS={results_path}",
        ],
        cwd=Path(__file__).parents[3],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
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
        "forbidden_retrieval_count": 0,
        "unexpected_outcome_count": 0,
    }
    assert report["baseline"]["passed"] is True


def test_retrieval_evaluation_fails_when_recall_exceeds_the_allowed_baseline_regression() -> None:
    report = evaluate_retrieval_quality(
        EvaluationDataset(
            version="1.0",
            questions={
                "termination-notice": {
                    "expected_outcome": "answer",
                    "expected_retrieval_sources": [
                        _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                    ],
                    "expected_citation_sources": [],
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
                "answer_status": "answered",
                "retrieved_sources": [],
                "citation_sources": [],
                "accepted_claims": [],
                "unauthorized_retrieved_sources": [],
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
                "expected_retrieval_sources": [
                    _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                ],
                "expected_citation_sources": [
                    _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                ],
                "expected_claims": [
                    {
                        "claim_id": "termination-notice",
                        "citation_sources": [
                            _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                        ],
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
                    "citation": {
                        "anchor_ids": ["msa-termination"],
                        "source_checksum": "checksum-v1",
                        "source_version": "v1",
                    },
                }
            ]
        },
        answer_response={
            "id": "turn-1",
            "question": "What is the notice period?",
            "created_at": "2026-01-01T00:00:00Z",
            "answer": {
                "status": "answered",
                "message": "90 days.",
                "claims": [
                    {
                        "text": "The notice period is 90 days.",
                        "citations": [
                            {
                                **_source(
                                    "11111111-1111-1111-1111-111111111111", "msa-termination"
                                ),
                                "supporting_quote": "90 days",
                            }
                        ],
                    }
                ],
            },
        },
        authorized_source_ids={
            _source_key(_source("11111111-1111-1111-1111-111111111111", "msa-termination"))
        },
        latency_ms=11,
        cost_usd=0.01,
    )

    assert observation == {
        "question_id": "termination-notice",
        "answer_status": "answered",
        "retrieved_sources": [_source("11111111-1111-1111-1111-111111111111", "msa-termination")],
        "citation_sources": [_source("11111111-1111-1111-1111-111111111111", "msa-termination")],
        "accepted_claims": [
            {
                "claim_id": "termination-notice",
                "citation_sources": [
                    _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                ],
            }
        ],
        "unauthorized_retrieved_sources": [],
        "latency_ms": 11.0,
        "cost_usd": 0.01,
    }


def test_runtime_adapter_rejects_a_citation_from_a_different_agreement() -> None:
    dataset = EvaluationDataset(
        version="1.0",
        questions={
            "termination-notice": {
                "expected_retrieval_sources": [
                    _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                ],
                "expected_citation_sources": [
                    _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                ],
                "expected_claims": [
                    {
                        "claim_id": "termination-notice",
                        "citation_sources": [
                            _source("11111111-1111-1111-1111-111111111111", "msa-termination")
                        ],
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
                    "citation": {
                        "anchor_ids": ["msa-termination"],
                        "source_checksum": "checksum-v1",
                        "source_version": "v1",
                    },
                }
            ]
        },
        answer_response={
            "answer": {
                "status": "partial",
                "message": "Partial answer.",
                "claims": [
                    {
                        "text": "The notice period is 90 days.",
                        "citations": [
                            {
                                **_source(
                                    "22222222-2222-2222-2222-222222222222", "msa-termination"
                                ),
                                "supporting_quote": "90 days",
                            }
                        ],
                    }
                ],
            },
        },
        authorized_source_ids={
            _source_key(_source("11111111-1111-1111-1111-111111111111", "msa-termination"))
        },
        latency_ms=11,
        cost_usd=0.01,
    )

    assert observation["citation_sources"] == []
    assert observation["accepted_claims"] == [
        cast(AcceptedClaim, {"claim_id": "runtime-claim-1", "citation_sources": []})
    ]


def test_load_observations_normalizes_captured_public_api_responses(tmp_path: Path) -> None:
    source = _source("11111111-1111-1111-1111-111111111111", "msa-termination")
    dataset = EvaluationDataset(
        version="1.0",
        questions={
            "termination-notice": {
                "expected_outcome": "answer",
                "expected_retrieval_sources": [source],
                "expected_citation_sources": [source],
                "expected_claims": [
                    {"claim_id": "termination-notice", "citation_sources": [source]}
                ],
            }
        },
        baseline={},
    )
    results_path = tmp_path / "runtime-results.json"
    results_path.write_text(
        json.dumps(
            {
                "dataset_version": "1.0",
                "runtime_observations": [
                    {
                        "question_id": "termination-notice",
                        "search_response": {
                            "items": [
                                {
                                    "agreement_id": source["agreement_id"],
                                    "citation": {
                                        "anchor_ids": [source["anchor_id"]],
                                        "source_checksum": source["source_checksum"],
                                        "source_version": source["source_version"],
                                    },
                                }
                            ]
                        },
                        "answer_response": {
                            "answer": {
                                "status": "answered",
                                "claims": [
                                    {
                                        "text": "Ninety days.",
                                        "citations": [{**source, "supporting_quote": "90 days"}],
                                    }
                                ],
                            }
                        },
                        "authorized_source_ids": [_source_key(source)],
                        "latency_ms": 2.0,
                        "cost_usd": 0.0,
                    }
                ],
            }
        )
    )

    assert load_observations(results_path, dataset) == [
        _observation("termination-notice", "answered", [source])
        | {
            "citation_sources": [source],
            "accepted_claims": [
                cast(
                    AcceptedClaim,
                    {"claim_id": "termination-notice", "citation_sources": [source]},
                )
            ],
            "latency_ms": 2.0,
        }
    ]


def test_evaluation_fails_when_a_permission_sensitive_case_retrieves_a_forbidden_source() -> None:
    source = _source("11111111-1111-1111-1111-111111111111", "board-pricing")
    report = evaluate_retrieval_quality(
        EvaluationDataset(
            version="1.0",
            questions={
                "board-only-pricing": {
                    "expected_outcome": "abstain",
                    "expected_retrieval_sources": [],
                    "expected_citation_sources": [],
                    "forbidden_sources": [source],
                    "expected_claims": [],
                }
            },
            baseline={"forbidden_retrieval_count": {"maximum": 0}},
        ),
        [_observation("board-only-pricing", "insufficient_evidence", [source])],
    )

    assert report["metrics"]["forbidden_retrieval_count"] == 1
    assert report["baseline"]["passed"] is False


def test_evaluation_fails_when_an_unanswerable_case_returns_an_answer() -> None:
    report = evaluate_retrieval_quality(
        EvaluationDataset(
            version="1.0",
            questions={
                "governing-law-absent": {
                    "expected_outcome": "abstain",
                    "expected_retrieval_sources": [],
                    "expected_citation_sources": [],
                    "expected_claims": [],
                }
            },
            baseline={"unexpected_outcome_count": {"maximum": 0}},
        ),
        [_observation("governing-law-absent", "answered", [])],
    )

    assert report["metrics"]["unexpected_outcome_count"] == 1
    assert report["baseline"]["passed"] is False


def test_evaluation_rejects_duplicates_and_reports_zero_unsupported_rate_without_claims() -> None:
    dataset = EvaluationDataset(
        version="1.0",
        questions={
            "governing-law-absent": {
                "expected_outcome": "abstain",
                "expected_retrieval_sources": [],
                "expected_citation_sources": [],
                "expected_claims": [],
            }
        },
        baseline={},
    )
    observation = _observation("governing-law-absent", "insufficient_evidence", [])

    single_report = evaluate_retrieval_quality(dataset, [observation])
    assert single_report["metrics"]["unsupported_accepted_claim_rate"] == 0.0

    try:
        evaluate_retrieval_quality(dataset, [observation, observation])
    except ValueError as error:
        assert str(error) == "Results contain duplicate question ids: ['governing-law-absent']"
    else:
        raise AssertionError("duplicate results must be rejected")


def _source(agreement_id: str, anchor_id: str, checksum: str = "checksum-v1") -> SourceReference:
    return {
        "agreement_id": agreement_id,
        "anchor_id": anchor_id,
        "source_checksum": checksum,
        "source_version": "v1",
    }


def _source_key(source: SourceReference) -> str:
    return "\x1f".join(
        (
            source["agreement_id"],
            source["source_checksum"],
            source["source_version"],
            source["anchor_id"],
        )
    )


def _observation(
    question_id: str, answer_status: str, retrieved_sources: list[SourceReference]
) -> EvaluationObservation:
    return {
        "question_id": question_id,
        "answer_status": answer_status,
        "retrieved_sources": retrieved_sources,
        "citation_sources": [],
        "accepted_claims": [],
        "unauthorized_retrieved_sources": [],
        "latency_ms": 1.0,
        "cost_usd": 0.0,
    }
