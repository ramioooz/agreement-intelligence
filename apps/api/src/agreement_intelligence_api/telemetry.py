"""Privacy-safe tracing primitives shared by API operations.

Only operational metadata is accepted here. Document text, prompts, model output,
credentials, and personal contact values are intentionally removed before they
can become span attributes.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from agreement_intelligence_platform.privacy import safe_event_metadata
from agreement_intelligence_platform.telemetry import operation_span as platform_operation_span
from opentelemetry.trace import Span


def redact_attributes(attributes: Mapping[str, object]) -> dict[str, object]:
    """Return attributes safe for telemetry exporters."""

    return safe_event_metadata(attributes)


@contextmanager
def operation_span(
    name: str,
    attributes: Mapping[str, object] | None = None,
    *,
    instrument: bool = True,
) -> Iterator[Span]:
    """Create a short-lived span with only redacted operational metadata."""

    with platform_operation_span(
        "agreement-intelligence.api",
        name,
        redact_attributes(attributes or {}),
        instrument=instrument,
    ) as span:
        yield span
