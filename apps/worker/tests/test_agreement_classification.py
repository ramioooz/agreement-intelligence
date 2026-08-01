from agreement_intelligence_worker.classification import classify_document


def test_classification_identifies_client_and_liquidity_provider_agreements() -> None:
    client = classify_document("Client Agreement margin client assets execution")
    provider = classify_document("Liquidity Provider Agreement executable prices market maker")
    unknown = classify_document("Commercial terms")

    assert client.family == "client_agreement"
    assert provider.family == "liquidity_provider_agreement"
    assert unknown.family == "unknown_needs_review"
