from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from agreement_intelligence_api.processing.queue import SQSProcessingQueuePublisher
from agreement_intelligence_api.processing.schemas import ProcessingJobResponse
from agreement_intelligence_api.telemetry import redact_attributes
from agreement_intelligence_platform.observability import extract_trace_context
from opentelemetry.context import attach, detach


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


def test_queue_messages_propagate_only_w3c_trace_context() -> None:
    @dataclass
    class QueueClient:
        request: dict[str, object] | None = None

        def send_message(self, **request: object) -> None:
            self.request = request

    client = QueueClient()
    publisher = SQSProcessingQueuePublisher(client=client, queue_url="https://example.test/queue")
    now = datetime.now(UTC)
    context_token = attach(
        extract_trace_context(
            {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": "vendor=value",
            }
        )
    )
    try:
        publisher.publish(
            ProcessingJobResponse(
                id=uuid4(),
                organization_id=uuid4(),
                workspace_id=uuid4(),
                agreement_id=uuid4(),
                state="queued",
                attempt_count=0,
                failure_category=None,
                failure_message=None,
                next_retry_at=None,
                queued_at=now,
                processing_started_at=None,
                completed_at=None,
                failed_at=None,
                created_at=now,
                updated_at=now,
                retry_permitted=False,
            ),
            idempotency_key="test-only",
            profile="analysis",
        )
    finally:
        detach(context_token)

    assert client.request is not None
    assert client.request["MessageAttributes"] == {
        "traceparent": {
            "DataType": "String",
            "StringValue": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        },
        "tracestate": {"DataType": "String", "StringValue": "vendor=value"},
    }
