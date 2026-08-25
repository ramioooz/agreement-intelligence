from agreement_intelligence_worker.ai_configuration import AIOperation, ConfigurationSnapshot
from agreement_intelligence_worker.model_gateway import GatewayJsonResponse, GatewayProvenance
from agreement_intelligence_worker.version_materiality import (
    MaterialityCandidate,
    assess_materiality,
    assess_materiality_with_model,
    augment_materiality,
)


def test_materiality_preserves_word_diff_and_marks_a_reduced_liability_cap_critical() -> None:
    candidate = MaterialityCandidate(
        change_type="modified",
        baseline_text="Supplier liability is capped at USD 2,000,000.",
        target_text="Supplier liability is capped at USD 250,000.",
        baseline_citation_ids=("v1-liability",),
        target_citation_ids=("v2-liability",),
        alignment_confidence=0.93,
        review_required=False,
    )
    configuration = ConfigurationSnapshot(
        operation=AIOperation.VERSION_MATERIALITY,
        version="2.1.0",
        prompt_template="Assess only cited changes.",
        schema={"type": "object"},
        model_route="openai:gpt-5.4-mini",
        parameters={"temperature": 0},
        schema_checksum="materiality-schema-v2",
    )
    gateway = _MaterialityGateway()

    result = assess_materiality_with_model(
        candidate,
        gateway=gateway,
        configuration=configuration,
    )

    assert result.severity == "critical"
    assert result.legal_concepts == ("liability", "numbers")
    assert result.review_required is True
    assert result.baseline_citation_ids == ("v1-liability",)
    assert result.target_citation_ids == ("v2-liability",)
    assert any(operation.kind == "replace" for operation in result.word_diff)
    assert result.model_rationale == "The reduced cap materially changes financial exposure."
    assert result.provider_provenance is not None
    assert result.provider_provenance["provider"] == "openai"
    assert result.provider_provenance["endpoint_kind"] == "hosted"
    assert result.provider_provenance["model"] == "gpt-5.4-mini"
    assert result.provider_provenance["configuration_version"] == "2.1.0"
    assert result.provider_provenance["latency_ms"] == 18
    assert result.provider_provenance["schema_checksum"] == "materiality-schema-v2"
    assert result.provider_provenance["model_route"] == "openai:gpt-5.4-mini"
    assert gateway.calls == 1


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


class _MaterialityGateway:
    def __init__(self) -> None:
        self.calls = 0

    def generate_json(self, **_kwargs: object) -> GatewayJsonResponse:
        self.calls += 1
        return GatewayJsonResponse(
            payload={
                "severity": "critical",
                "rationale": "The reduced cap materially changes financial exposure.",
                "citation_ids": ["v1-liability", "v2-liability"],
            },
            provenance=GatewayProvenance(
                provider="openai",
                endpoint_kind="hosted",
                model="gpt-5.4-mini",
                configuration_version="2.1.0",
                latency_ms=18,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                cost_usd=None,
                retry_outcome="not_retried",
                fallback_outcome="not_needed",
                safe_failure_reason=None,
            ),
        )
