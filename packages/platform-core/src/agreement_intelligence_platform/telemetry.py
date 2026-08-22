"""Small, privacy-safe OpenTelemetry bootstrap shared by Python services."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from threading import Lock
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span

from agreement_intelligence_platform.privacy import safe_event_metadata

_provider: TracerProvider | None = None
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

    global _provider
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
        _provider = provider
        return provider


@contextmanager
def operation_span(
    tracer_name: str,
    span_name: str,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[Span]:
    """Use an active recording span or create an explicit operation span."""

    current = trace.get_current_span()
    if current.is_recording():
        yield current
        return
    tracer = trace.get_tracer(tracer_name)
    with tracer.start_as_current_span(
        span_name,
        attributes=cast(Any, safe_event_metadata(attributes or {})),
    ) as span:
        yield span
