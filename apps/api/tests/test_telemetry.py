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


def test_telemetry_uses_recursive_fail_closed_event_metadata() -> None:
    safe = redact_attributes(
        {
            "Document": {"Text": "private agreement"},
            "request": {
                "Credentials": {"Authorization": "Bearer private-token"},
                "custom_context": "not approved for export",
            },
            "CORRELATION_ID": "correlation-123",
            "status": "completed",
            "model_config_version": "model-gateway.v1",
            "duration_ms": 42,
            "token_counts": {"input_tokens": 13, "output_tokens": 8},
        }
    )

    assert safe == {
        "CORRELATION_ID": "correlation-123",
        "status": "completed",
        "model_config_version": "model-gateway.v1",
        "duration_ms": 42,
        "token_counts": {"input_tokens": 13, "output_tokens": 8},
    }
