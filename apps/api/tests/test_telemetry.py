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


def test_telemetry_exports_only_approved_reason_codes() -> None:
    safe = redact_attributes(
        {
            "reason_code": "risk_exception",
            "reason": "contact legal@example.test with token sk-proj-demo-secret",
            "policy_override_note": "This Agreement is entered into by the parties.",
            "nested": {"reason_code": 17},
        }
    )

    assert safe == {"reason_code": "risk_exception"}
