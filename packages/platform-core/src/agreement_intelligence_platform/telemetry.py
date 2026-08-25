"""Small, privacy-safe OpenTelemetry bootstrap shared by Python services."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from time import perf_counter
from typing import Any, cast

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode

from agreement_intelligence_platform.observability import record_metric
from agreement_intelligence_platform.privacy import safe_event_metadata

_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_provider_lock = Lock()


def configure_telemetry(
    service_name: str,
    *,
    environment: Mapping[str, str],
    span_exporter: SpanExporter | None = None,
) -> TracerProvider | None:
    """Configure one process-wide SDK provider when an exporter is available.

    An absent collector endpoint is a supported local mode. Tests may inject an
    in-memory exporter without changing production configuration.
    """

    global _meter_provider, _provider
    endpoint = environment.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if span_exporter is None and not endpoint:
        return None
    with _provider_lock:
        if _provider is not None:
            if span_exporter is not None:
                _provider.add_span_processor(SimpleSpanProcessor(span_exporter))
            return _provider
        exporter = span_exporter or OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        processor = (
            SimpleSpanProcessor(exporter)
            if span_exporter is not None
            else BatchSpanProcessor(exporter)
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        if _meter_provider is None:
            metric_reader = (
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics")
                )
                if endpoint
                else None
            )
            _meter_provider = MeterProvider(
                resource=Resource.create({"service.name": service_name}),
                metric_readers=() if metric_reader is None else (metric_reader,),
            )
            metrics.set_meter_provider(_meter_provider)
        _provider = provider
        return provider


@contextmanager
def operation_span(
    tracer_name: str,
    span_name: str,
    attributes: Mapping[str, object] | None = None,
    *,
    outcome_getter: Callable[[], str] | None = None,
) -> Iterator[Span]:
    """Create and export a named child span for every operation boundary."""

    tracer = trace.get_tracer(tracer_name)
    safe_attributes = cast(Any, safe_event_metadata(attributes or {}))
    operation = safe_attributes.get("operation", span_name)
    bounded_operation = operation if isinstance(operation, str) else "other"
    started_at = perf_counter()
    with tracer.start_as_current_span(
        span_name,
        attributes=safe_attributes,
    ) as span:
        try:
            yield span
        except Exception as error:
            span.set_attribute("outcome", "failure")
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            record_metric(
                "agreement_intelligence.operation.error_count",
                1,
                operation=bounded_operation,
                outcome="failure",
            )
            raise
        else:
            initial_outcome = safe_attributes.get("outcome", "success")
            outcome = outcome_getter() if outcome_getter is not None else initial_outcome
            metric_outcome = (
                outcome
                if isinstance(outcome, str)
                and outcome in {"success", "failure", "retry", "skipped"}
                else "failure"
            )
            span.set_attribute("outcome", metric_outcome)
            record_metric(
                "agreement_intelligence.operation.count",
                1,
                operation=bounded_operation,
                outcome=metric_outcome,
            )
            record_metric(
                "agreement_intelligence.operation.duration_ms",
                round((perf_counter() - started_at) * 1_000),
                operation=bounded_operation,
                outcome=metric_outcome,
            )
