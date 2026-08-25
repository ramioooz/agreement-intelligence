"""Privacy-safe OpenTelemetry propagation, attributes, and aggregate metrics."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Final

from opentelemetry import metrics, propagate
from opentelemetry.context import Context

from agreement_intelligence_platform.privacy import safe_event_metadata

_OPERATIONS: Final = frozenset(
    {
        "database.query",
        "evaluation.run",
        "http.request",
        "mcp.tool",
        "model.embed",
        "model.generate",
        "queue.publish",
        "queue.receive",
        "qa.answer",
        "retrieval.search",
        "worker.processing",
        "workflow.transition",
    }
)
_OUTCOMES: Final = frozenset({"success", "failure", "retry", "skipped"})
_SPAN_KEYS: Final = frozenset(
    {
        "attempt_count",
        "cost_usd",
        "correlation_id",
        "endpoint_kind",
        "evaluation_outcome",
        "input_tokens",
        "latency_ms",
        "model",
        "model_configuration_version",
        "operation",
        "outcome",
        "output_tokens",
        "queue_age_ms",
        "provider",
        "retrieval_result_count",
        "retry_count",
        "status_code",
        "tool_name",
        "total_tokens",
        "workflow_state",
    }
)
_METRICS: Final = frozenset(
    {
        "agreement_intelligence.operation.count",
        "agreement_intelligence.operation.duration_ms",
        "agreement_intelligence.operation.error_count",
        "agreement_intelligence.queue.age_ms",
        "agreement_intelligence.retry.count",
        "agreement_intelligence.model.tokens",
        "agreement_intelligence.model.cost_usd",
        "agreement_intelligence.retrieval.result_count",
        "agreement_intelligence.evaluation.count",
        "agreement_intelligence.workflow.transition_count",
    }
)
_meter = metrics.get_meter("agreement-intelligence.platform")
_counters: dict[str, metrics.Counter] = {}
_histograms: dict[str, metrics.Histogram] = {}


def inject_trace_context(headers: MutableMapping[str, str]) -> None:
    """Add only the W3C trace headers for the active context to a message carrier."""

    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    for key in ("traceparent", "tracestate"):
        value = carrier.get(key)
        if value:
            headers[key] = value


def extract_trace_context(headers: Mapping[str, str]) -> Context:
    """Read W3C trace headers from an HTTP or queue carrier."""

    return propagate.extract({key.casefold(): value for key, value in headers.items()})


def metric_attributes(operation: str, outcome: str) -> dict[str, str]:
    """Return the bounded labels shared by every aggregate metric."""

    return {
        "operation": operation if operation in _OPERATIONS else "other",
        "outcome": outcome if outcome in _OUTCOMES else "failure",
    }


def safe_span_attributes(attributes: Mapping[str, object]) -> dict[str, object]:
    """Filter spans to the fixed operational schema before exporter handoff."""

    bounded = {key: value for key, value in attributes.items() if key in _SPAN_KEYS}
    safe = safe_event_metadata(bounded)
    operation = safe.get("operation")
    if isinstance(operation, str) and operation not in _OPERATIONS:
        safe["operation"] = "other"
    outcome = safe.get("outcome")
    if isinstance(outcome, str) and outcome not in _OUTCOMES:
        safe["outcome"] = "failure"
    return safe


def record_metric(metric_name: str, value: int | float, *, operation: str, outcome: str) -> None:
    """Record one approved aggregate metric with bounded labels only."""

    if metric_name not in _METRICS:
        raise ValueError(f"unsupported observability metric: {metric_name}")
    attributes = metric_attributes(operation, outcome)
    if metric_name.endswith(("duration_ms", "age_ms", "cost_usd", "result_count")):
        histogram = _histograms.setdefault(metric_name, _meter.create_histogram(metric_name))
        histogram.record(value, attributes)
        return
    counter = _counters.setdefault(metric_name, _meter.create_counter(metric_name))
    counter.add(value, attributes)
