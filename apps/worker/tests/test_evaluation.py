from agreement_intelligence_worker.evaluation import evaluate


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
