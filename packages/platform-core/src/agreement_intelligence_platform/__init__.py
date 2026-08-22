"""Shared platform policies for Agreement Intelligence services."""

from agreement_intelligence_platform.privacy import (
    DataClass,
    classify_key,
    redact_mapping,
    retention_policy_metadata,
    safe_event_metadata,
)

__all__ = [
    "DataClass",
    "classify_key",
    "redact_mapping",
    "retention_policy_metadata",
    "safe_event_metadata",
]

__version__ = "0.1.0"
