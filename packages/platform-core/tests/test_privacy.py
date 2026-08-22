import pytest
from agreement_intelligence_platform.privacy import (
    DataClass,
    classify_key,
    redact_mapping,
    retention_policy_metadata,
    safe_event_metadata,
)


@pytest.mark.parametrize(
    "key",
    [
        "document.text",
        "prompt",
        "provider.output",
        "provider_output",
        "authorization",
        "access_token",
        "api_key",
        "password",
        "email",
        "request.credentials",
    ],
)
def test_classify_key_marks_confidential_content_and_credentials_as_prohibited(
    key: str,
) -> None:
    assert classify_key(key) is DataClass.PROHIBITED


def test_redact_mapping_handles_exact_and_dotted_keys() -> None:
    redacted = redact_mapping(
        {
            "document.text": "private agreement text",
            "prompt": "private model prompt",
            "provider_output": "private model response",
            "authorization": "Bearer private-token",
            "access_token": "private-access-token",
            "api_key": "private-provider-key",
            "password": "private-password",
            "email": "private-person@example.test",
            "correlation_id": "correlation-123",
            "status": "completed",
            "model_config_version": "model-gateway.v1",
            "model_configuration_version": "model-gateway.v1",
            "duration": 0.084,
            "duration_ms": 84,
            "input_tokens": 21,
            "output_tokens": 13,
        }
    )

    assert redacted == {
        "document.text": "[redacted]",
        "prompt": "[redacted]",
        "provider_output": "[redacted]",
        "authorization": "[redacted]",
        "access_token": "[redacted]",
        "api_key": "[redacted]",
        "password": "[redacted]",
        "email": "[redacted]",
        "correlation_id": "correlation-123",
        "status": "completed",
        "model_config_version": "model-gateway.v1",
        "model_configuration_version": "model-gateway.v1",
        "duration": 0.084,
        "duration_ms": 84,
        "input_tokens": 21,
        "output_tokens": 13,
    }


def test_redact_mapping_recurses_through_nested_mappings_and_sequences() -> None:
    redacted = redact_mapping(
        {
            "Document": {"Text": "private nested agreement text"},
            "request": {
                "Credentials": {
                    "Api_Key": "private-nested-key",
                    "Password": "private-nested-password",
                },
                "events": [
                    {
                        "Provider_Output": "private nested model response",
                        "STATUS": "failed",
                    }
                ],
            },
            "CORRELATION_ID": "correlation-456",
            "token_counts": {"input_tokens": 8, "output_tokens": 5},
        }
    )

    assert redacted == {
        "Document": {"Text": "[redacted]"},
        "request": {
            "Credentials": "[redacted]",
            "events": [
                {
                    "Provider_Output": "[redacted]",
                    "STATUS": "failed",
                }
            ],
        },
        "CORRELATION_ID": "correlation-456",
        "token_counts": {"input_tokens": 8, "output_tokens": 5},
    }


def test_restricted_scalar_sequences_fail_closed_while_nested_events_are_inspected() -> None:
    values = {
        "custom_values": ["private value"],
        "events": [{"status": "completed", "prompt": "private prompt"}],
    }

    assert redact_mapping(values) == {
        "custom_values": ["[redacted]"],
        "events": [{"status": "completed", "prompt": "[redacted]"}],
    }
    assert safe_event_metadata(values) == {
        "events": [{"status": "completed"}],
    }


def test_arbitrary_log_messages_fail_closed_even_without_sensitive_keywords() -> None:
    values = {"message": "Either party may terminate with thirty days notice."}

    assert redact_mapping(values) == {"message": "[redacted]"}
    assert safe_event_metadata(values) == {}


def test_safe_event_metadata_removes_prohibited_and_unapproved_restricted_values() -> None:
    metadata = safe_event_metadata(
        {
            "Document": {"Text": "private nested agreement text"},
            "Prompt": "private prompt",
            "provider_output": "private response",
            "Authorization": "Bearer private-token",
            "Access_Token": "private-access-token",
            "API_KEY": "private-provider-key",
            "Password": "private-password",
            "EMAIL": "private-person@example.test",
            "custom_context": "not approved for emission",
            "correlation_id": "correlation-789",
            "status": "completed",
            "model_config_version": "model-gateway.v2",
            "duration_ms": 144,
            "token_counts": {"input_tokens": 34, "output_tokens": 21},
        }
    )

    assert metadata == {
        "correlation_id": "correlation-789",
        "status": "completed",
        "model_config_version": "model-gateway.v2",
        "duration_ms": 144,
        "token_counts": {"input_tokens": 34, "output_tokens": 21},
    }


def test_retention_policy_metadata_parses_positive_integer_settings() -> None:
    metadata = retention_policy_metadata(
        {
            "AUDIT_RETENTION_DAYS": "2555",
            "TELEMETRY_RETENTION_DAYS": "30",
            "APPLICATION_LOG_RETENTION_DAYS": "14",
        }
    )

    assert metadata == {
        "application_log_retention_days": 14,
        "audit_retention_days": 2555,
        "immutable_business_audit_auto_delete": False,
        "telemetry_retention_days": 30,
    }


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "thirty"])
def test_retention_policy_metadata_rejects_non_positive_integers(value: str) -> None:
    with pytest.raises(ValueError, match="must be a positive integer"):
        retention_policy_metadata(
            {
                "AUDIT_RETENTION_DAYS": value,
                "TELEMETRY_RETENTION_DAYS": "30",
                "APPLICATION_LOG_RETENTION_DAYS": "14",
            }
        )
