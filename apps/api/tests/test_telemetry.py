from agreement_intelligence_api.telemetry import redact_attributes


def test_telemetry_redacts_document_and_credential_attributes() -> None:
    safe = redact_attributes(
        {
            "document_text": "private agreement",
            "prompt": "private prompt",
            "api_key": "secret",
            "email": "person@example.test",
            "tenant_id": "tenant-1",
            "latency_ms": 42,
        }
    )

    assert safe == {"tenant_id": "tenant-1", "latency_ms": 42}
