from __future__ import annotations

from pathlib import Path
from subprocess import run

from agreement_intelligence_worker.analysis_provider import ProviderAnalysis
from agreement_intelligence_worker.evaluation import evaluate
from agreement_intelligence_worker.provider_smoke import main as provider_smoke_main
from pytest import CaptureFixture, MonkeyPatch


def test_evaluation_reports_a_repeatable_classification_baseline() -> None:
    report = evaluate(
        [
            {"text": "Client Agreement margin", "expected_family": "client_agreement"},
            {
                "text": "Liquidity Provider executable prices",
                "expected_family": "liquidity_provider_agreement",
            },
        ]
    )

    assert report["classification_accuracy"] == 1.0
    assert report["cases"] == 2


def test_evaluation_compares_deterministic_and_fake_hybrid_results() -> None:
    report = evaluate(
        [
            {"text": "Client Agreement margin", "expected_family": "client_agreement"},
            {
                "text": "Liquidity Provider executable prices",
                "expected_family": "liquidity_provider_agreement",
            },
        ],
        provider=FakeProvider(),
    )

    assert report["modes"] == {"deterministic", "hybrid"}
    assert report["hybrid_classification_accuracy"] == 1.0


def test_provider_smoke_requires_a_configured_key(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        provider_smoke_main()
    except SystemExit as error:
        assert error.code == 1
    else:
        raise AssertionError("provider smoke must stop when no key is configured")

    assert "OPENAI_API_KEY is required for provider smoke checks" in capsys.readouterr().err


def test_provider_smoke_uses_the_selected_environment_file() -> None:
    result = run(
        ["make", "--just-print", "provider-smoke", "STACK_ENV_FILE=smoke.env"],
        cwd=Path(__file__).parents[3],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert '--env-file "smoke.env"' in result.stdout


class FakeProvider:
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis:
        anchor_id, text = blocks[0]
        family = (
            "liquidity_provider_agreement"
            if "liquidity provider" in text.lower()
            else "client_agreement"
        )
        return ProviderAnalysis(
            classification={
                "family": family,
                "confidence": 0.9,
                "rationale": text,
                "citation_anchor_ids": [anchor_id],
            },
            clauses=[],
            risks=[],
            summaries={
                "business": {
                    "claim": text,
                    "citation_anchor_ids": [anchor_id],
                },
                "legal": {
                    "claim": text,
                    "citation_anchor_ids": [anchor_id],
                },
            },
            model="fake-model",
            input_tokens=10,
            output_tokens=20,
            latency_ms=1,
        )
