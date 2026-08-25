from __future__ import annotations

import json
from pathlib import Path

import pytest
from agreement_intelligence_worker.unified_evaluation import evaluate_release


def test_release_gate_passes_all_capabilities_without_rewriting_the_baseline(
    tmp_path: Path,
) -> None:
    manifest, baseline, results = _write_inputs(tmp_path)
    baseline_before = baseline.read_bytes()

    report = evaluate_release(manifest, baseline, results)

    assert report["passed"] is True
    assert report["failures"] == []
    assert set(report["capabilities"]) == {
        "classification",
        "comparison",
        "extraction",
        "grounding",
        "guardrails",
        "retrieval",
    }
    assert report["metrics"]["grounding.citation_precision"] == 1.0
    assert report["metrics"]["retrieval.unauthorized_retrieval_count"] == 0
    assert report["metrics"]["grounding.unsupported_accepted_claims"] == 0
    assert report["changed_cases"] == []
    assert report["usage"] == {
        "cost_usd_total": 0.003,
        "latency_ms_total": 210.0,
        "tokens_total": 350,
    }
    assert baseline.read_bytes() == baseline_before


def test_release_gate_reports_threshold_regressions_and_changed_cases(tmp_path: Path) -> None:
    manifest, baseline, results = _write_inputs(tmp_path)
    payload = json.loads(results.read_text())
    payload["cases"][3].update(
        {
            "fingerprint": "grounding-v2",
            "change_summary": "Grounded answer lost its required citation.",
            "metrics": {
                "citation_precision": 0.5,
                "unsupported_accepted_claims": 1,
            },
        }
    )
    payload["cases"][4]["metrics"]["recall_at_5"] = 0.74
    payload["cases"][4]["metrics"]["unauthorized_retrieval_count"] = 1
    results.write_text(json.dumps(payload))

    report = evaluate_release(manifest, baseline, results)

    assert report["passed"] is False
    assert report["changed_cases"] == [
        {
            "capability": "grounding",
            "current_fingerprint": "grounding-v2",
            "id": "grounding-citations",
            "previous_fingerprint": "grounding-v1",
            "summary": "Grounded answer lost its required citation.",
        }
    ]
    assert report["failures"] == [
        "grounding.citation_precision is below its accepted minimum 1.0 (observed 0.5)",
        "grounding.unsupported_accepted_claims exceeds its accepted maximum 0.0 (observed 1.0)",
        "retrieval.recall_at_5 regressed more than 0.05 from 0.8 (observed 0.74)",
        "retrieval.unauthorized_retrieval_count exceeds its accepted maximum 0.0 (observed 1.0)",
    ]


def test_release_gate_refuses_to_use_the_accepted_baseline_as_runtime_results(
    tmp_path: Path,
) -> None:
    manifest, baseline, _ = _write_inputs(tmp_path)

    with pytest.raises(ValueError, match="accepted baseline cannot be used as results"):
        evaluate_release(manifest, baseline, baseline)


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest = tmp_path / "manifest.json"
    baseline = tmp_path / "accepted-baseline.json"
    results = tmp_path / "results.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "unified-v1",
                "required_capabilities": [
                    "classification",
                    "extraction",
                    "grounding",
                    "retrieval",
                    "comparison",
                    "guardrails",
                ],
            }
        )
    )
    baseline.write_text(
        json.dumps(
            {
                "version": "unified-v1",
                "case_fingerprints": {
                    "classification-family": "classification-v1",
                    "comparison-materiality": "comparison-v1",
                    "extraction-clauses": "extraction-v1",
                    "grounding-citations": "grounding-v1",
                    "guardrails-injection": "guardrails-v1",
                    "retrieval-portfolio": "retrieval-v1",
                },
                "metrics": {
                    "classification.accuracy": {"accepted": 1.0, "minimum": 0.9},
                    "comparison.critical_material_change_recall": {
                        "accepted": 1.0,
                        "minimum": 1.0,
                    },
                    "extraction.clause_f1": {"accepted": 0.9, "minimum": 0.85},
                    "grounding.citation_precision": {"accepted": 1.0, "minimum": 1.0},
                    "grounding.unsupported_accepted_claims": {
                        "accepted": 0,
                        "maximum": 0,
                    },
                    "guardrails.unsafe_acceptances": {"accepted": 0, "maximum": 0},
                    "retrieval.recall_at_5": {
                        "accepted": 0.8,
                        "maximum_regression": 0.05,
                    },
                    "retrieval.unauthorized_retrieval_count": {
                        "accepted": 0,
                        "maximum": 0,
                    },
                },
            }
        )
    )
    results.write_text(
        json.dumps(
            {
                "version": "unified-v1",
                "cases": [
                    _case(
                        "classification-family",
                        "classification",
                        "classification-v1",
                        {"accuracy": 1.0},
                    ),
                    _case(
                        "comparison-materiality",
                        "comparison",
                        "comparison-v1",
                        {"critical_material_change_recall": 1.0},
                    ),
                    _case("extraction-clauses", "extraction", "extraction-v1", {"clause_f1": 0.9}),
                    _case(
                        "grounding-citations",
                        "grounding",
                        "grounding-v1",
                        {
                            "citation_precision": 1.0,
                            "unsupported_accepted_claims": 0,
                        },
                    ),
                    _case(
                        "retrieval-portfolio",
                        "retrieval",
                        "retrieval-v1",
                        {
                            "recall_at_5": 0.8,
                            "unauthorized_retrieval_count": 0,
                        },
                    ),
                    _case(
                        "guardrails-injection",
                        "guardrails",
                        "guardrails-v1",
                        {"unsafe_acceptances": 0},
                    ),
                ],
            }
        )
    )
    return manifest, baseline, results


def _case(
    identifier: str,
    capability: str,
    fingerprint: str,
    metrics: dict[str, float],
) -> dict[str, object]:
    return {
        "id": identifier,
        "capability": capability,
        "fingerprint": fingerprint,
        "metrics": metrics,
        "latency_ms": 35.0,
        "tokens": 350 if capability == "grounding" else 0,
        "cost_usd": 0.003 if capability == "grounding" else 0,
    }
