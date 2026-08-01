from agreement_intelligence_worker.classification import classify_document


def test_classification_distinguishes_agreements_non_agreement_material_and_uncertainty() -> None:
    client = classify_document("Client Agreement margin client assets execution")
    provider = classify_document("Liquidity Provider Agreement executable prices market maker")
    unknown = classify_document("Commercial terms")
    resume = classify_document(
        "Senior engineer resume with client projects, skills, work experience and education"
    )

    assert client.family == "client_agreement"
    assert provider.family == "liquidity_provider_agreement"
    assert unknown.family == "unknown_needs_review"
    assert resume.family == "non_agreement_material"
