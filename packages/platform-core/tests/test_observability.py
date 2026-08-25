from agreement_intelligence_platform.observability import (
    extract_trace_context,
    inject_trace_context,
    metric_attributes,
    safe_span_attributes,
)
from agreement_intelligence_platform.telemetry import configure_telemetry, operation_span
from opentelemetry import trace
from opentelemetry.context import attach, detach
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def test_synthetic_trace_context_flows_from_api_to_queue_worker_retrieval_and_model() -> None:
    api_context = extract_trace_context({"traceparent": TRACEPARENT, "tracestate": "vendor=value"})
    api_token = attach(api_context)
    queue_headers: dict[str, str] = {}
    inject_trace_context(queue_headers)
    detach(api_token)

    worker_context = extract_trace_context(queue_headers)
    worker_token = attach(worker_context)
    retrieval_headers: dict[str, str] = {}
    inject_trace_context(retrieval_headers)
    detach(worker_token)

    assert queue_headers["traceparent"] == TRACEPARENT
    assert queue_headers["tracestate"] == "vendor=value"
    assert retrieval_headers["traceparent"] == TRACEPARENT
    assert retrieval_headers["tracestate"] == "vendor=value"


def test_operation_span_exports_a_named_child_span() -> None:
    exporter = InMemorySpanExporter()
    configure_telemetry("test-observability", environment={}, span_exporter=exporter)
    tracer = trace.get_tracer("test-observability")

    with (
        tracer.start_as_current_span("request"),
        operation_span("test-observability", "queue.publish", {"operation": "queue.publish"}),
    ):
        pass

    assert [span.name for span in exporter.get_finished_spans()] == ["queue.publish", "request"]


def test_observability_attributes_are_low_cardinality_and_fail_closed() -> None:
    assert metric_attributes("queue.publish", "success") == {
        "operation": "queue.publish",
        "outcome": "success",
    }
    assert safe_span_attributes(
        {
            "operation": "model.generate",
            "outcome": "success",
            "document_text": "Confidential agreement text",
            "prompt": "Summarize the agreement",
            "provider_output": "Private output",
            "email": "owner@example.test",
            "agreement_title": "Acquisition agreement",
            "job_id": "raw-unbounded-id",
            "input_tokens": 12,
        }
    ) == {
        "operation": "model.generate",
        "outcome": "success",
        "input_tokens": 12,
    }
