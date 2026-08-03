"""Privacy-safe tracing primitives shared by API operations.

Only operational metadata is accepted here. Document text, prompts, model output,
credentials, and personal contact values are intentionally removed before they
can become span attributes.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

from opentelemetry.trace import get_tracer

_SENSITIVE_KEYS = frozenset(
    {
        "document_text",
        "prompt",
        "provider_output",
        "access_token",
        "authorization",
        "api_key",
        "secret",
        "email",
        "raw_text",
    }
)


def redact_attributes(attributes: Mapping[str, object]) -> dict[str, object]:
    """Return attributes safe for telemetry exporters."""

    return {key: value for key, value in attributes.items() if key.lower() not in _SENSITIVE_KEYS}


@contextmanager
def operation_span(name: str, attributes: Mapping[str, object] | None = None) -> Iterator[None]:
    """Create a short-lived span with only redacted operational metadata."""

    tracer = get_tracer("agreement-intelligence.api")
    with tracer.start_as_current_span(
        name, attributes=cast(Any, redact_attributes(attributes or {}))
    ):
        yield
