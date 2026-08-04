from agreement_intelligence_worker.version_materiality import (
    MaterialityCandidate,
    assess_materiality,
    augment_materiality,
)


def test_materiality_preserves_word_diff_and_marks_a_reduced_liability_cap_critical() -> None:
    result = assess_materiality(
        MaterialityCandidate(
            change_type="modified",
            baseline_text="Supplier liability is capped at USD 2,000,000.",
            target_text="Supplier liability is capped at USD 250,000.",
            baseline_citation_ids=("v1-liability",),
            target_citation_ids=("v2-liability",),
            alignment_confidence=0.93,
            review_required=False,
        )
    )

    assert result.severity == "critical"
    assert result.legal_concepts == ("liability", "numbers")
    assert result.review_required is True
    assert result.baseline_citation_ids == ("v1-liability",)
    assert result.target_citation_ids == ("v2-liability",)
    assert any(operation.kind == "replace" for operation in result.word_diff)


def test_materiality_keeps_low_confidence_alignment_visible_without_model_output() -> None:
    result = assess_materiality(
        MaterialityCandidate(
            change_type="moved",
            baseline_text="The parties will retain records for seven years.",
            target_text="The parties will retain records for seven years.",
            baseline_citation_ids=("v1-records",),
            target_citation_ids=("v2-records",),
            alignment_confidence=0.51,
            review_required=True,
        )
    )

    assert result.severity == "medium"
    assert result.review_required is True
    assert result.provider_provenance is None
    assert result.model_rationale is None


def test_invalid_model_enrichment_falls_back_without_losing_deterministic_evidence() -> None:
    baseline = assess_materiality(
        MaterialityCandidate(
            change_type="modified",
            baseline_text="Either party may terminate with 30 days notice.",
            target_text="Either party may terminate with 10 days notice.",
            baseline_citation_ids=("v1-termination",),
            target_citation_ids=("v2-termination",),
            alignment_confidence=1.0,
            review_required=False,
        )
    )

    result = augment_materiality(
        baseline,
        {"severity": "low", "rationale": "unsupported", "citation_ids": ["not-an-anchor"]},
        provider_provenance={"model": "test-model", "latency_ms": 4},
    )

    assert result == baseline
