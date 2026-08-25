"""Fail-closed classification and redaction for emitted service metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from enum import StrEnum

REDACTED = "[redacted]"


class DataClass(StrEnum):
    PROHIBITED = "prohibited"
    RESTRICTED = "restricted"
    OPERATIONAL = "operational"


_PROHIBITED_KEYS = frozenset(
    {
        "agreement_text",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "document_text",
        "email",
        "first_name",
        "last_name",
        "password",
        "prompt",
        "provider.output",
        "provider_output",
        "raw_text",
        "secret",
        "subject",
        "text",
        "username",
    }
)

_OPERATIONAL_KEYS = frozenset(
    {
        "archived",
        "application_log_retention_days",
        "attempt_count",
        "audit_retention_days",
        "duration_ms",
        "duration",
        "event",
        "input_tokens",
        "guardrail_policy_version",
        "guardrail_reason_codes",
        "guardrail_status",
        "immutable_business_audit_auto_delete",
        "latency_ms",
        "level",
        "limit",
        "message",
        "method",
        "model",
        "model_config_version",
        "model_configuration_version",
        "operation",
        "outcome",
        "output_tokens",
        "path",
        "processing_state",
        "query_present",
        "reason_code",
        "service",
        "state",
        "status",
        "status_code",
        "cost_usd",
        "endpoint_kind",
        "evaluation_outcome",
        "queue_age_ms",
        "provider",
        "retrieval_result_count",
        "retry_count",
        "tool_name",
        "workflow_state",
        "telemetry_retention_days",
        "token_count",
        "total_tokens",
        "traceparent",
    }
)

_ALLOWED_RESTRICTED_KEYS = frozenset(
    {
        "agreement_id",
        "citation_id",
        "correlation_id",
        "job_id",
        "organization_id",
        "processing_job_id",
        "span_id",
        "tenant_id",
        "trace_id",
        "workflow_event_id",
        "workspace_id",
    }
)

_ALLOWED_LOG_MESSAGES = frozenset(
    {
        "processing job queued",
        "processing message handling failed",
        "request completed",
        "review workflow queued",
        "worker started",
        "worker stopped",
    }
)

_APPROVED_REASON_CODES = frozenset(
    {
        "business_exception",
        "contractual_requirement",
        "jurisdictional_requirement",
        "risk_exception",
        "other",
    }
)

_RETENTION_DEFAULTS = {
    "APPLICATION_LOG_RETENTION_DAYS": 14,
    "AUDIT_RETENTION_DAYS": 2555,
    "TELEMETRY_RETENTION_DAYS": 30,
}


def classify_key(key: str) -> DataClass:
    """Classify a metadata key using its full dotted path and leaf name."""

    normalized = _normalize_key(key)
    leaf = normalized.rsplit(".", 1)[-1]
    candidates = {normalized, leaf}

    if candidates & _PROHIBITED_KEYS or leaf.endswith(("_password", "_secret", "_token")):
        return DataClass.PROHIBITED
    if candidates & _OPERATIONAL_KEYS:
        return DataClass.OPERATIONAL
    return DataClass.RESTRICTED


def redact_mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Return a structure-preserving copy with unsafe scalar values redacted."""

    redacted = _redact_node(values, parent_key="")
    assert isinstance(redacted, dict)
    return redacted


def safe_event_metadata(values: Mapping[str, object]) -> dict[str, object]:
    """Return only metadata approved for logs, audit attributes, and telemetry."""

    safe = _safe_node(values, parent_key="")
    return safe if isinstance(safe, dict) else {}


def retention_policy_metadata(
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Parse configured retention periods into safe operational policy metadata.

    The audit value documents the intended retention period. It does not schedule
    deletion of immutable business audit records.
    """

    source = os.environ if environment is None else environment
    parsed: dict[str, object] = {"immutable_business_audit_auto_delete": False}
    for variable, default in _RETENTION_DEFAULTS.items():
        raw_value = source.get(variable, str(default))
        if not raw_value.isdecimal() or int(raw_value) <= 0:
            raise ValueError(f"{variable} must be a positive integer")
        parsed[variable.casefold()] = int(raw_value)
    return safe_event_metadata(parsed)


def _redact_node(node: object, parent_key: str) -> object:
    if isinstance(node, Mapping):
        redacted: dict[str, object] = {}
        for key, value in node.items():
            dotted_key = _join_key(parent_key, key)
            classification = classify_key(dotted_key)
            if classification is DataClass.PROHIBITED:
                redacted[key] = REDACTED
            elif isinstance(value, Mapping) or _is_sequence(value):
                redacted[key] = _redact_node(value, dotted_key)
            elif classification is DataClass.OPERATIONAL or _is_allowed_restricted(dotted_key):
                redacted[key] = REDACTED if _unsafe_scalar(dotted_key, value) else value
            else:
                redacted[key] = REDACTED
        return redacted
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        parent_is_allowed = classify_key(
            parent_key
        ) is DataClass.OPERATIONAL or _is_allowed_restricted(parent_key)
        return [
            _redact_node(item, parent_key)
            if isinstance(item, Mapping) or _is_sequence(item)
            else item
            if parent_is_allowed and not _unsafe_scalar(parent_key, item)
            else REDACTED
            for item in node
        ]
    return node


def _safe_node(node: object, parent_key: str) -> object | None:
    if isinstance(node, Mapping):
        safe: dict[str, object] = {}
        for key, value in node.items():
            dotted_key = _join_key(parent_key, key)
            classification = classify_key(dotted_key)
            if classification is DataClass.PROHIBITED:
                continue
            if isinstance(value, Mapping) or _is_sequence(value):
                child = _safe_node(value, dotted_key)
                if child not in ({}, [], None):
                    safe[key] = child
            elif (
                classification is DataClass.OPERATIONAL or _is_allowed_restricted(dotted_key)
            ) and not _unsafe_scalar(dotted_key, value):
                safe[key] = value
        return safe
    if isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        parent_is_allowed = classify_key(
            parent_key
        ) is DataClass.OPERATIONAL or _is_allowed_restricted(parent_key)
        safe_items: list[object] = []
        for value in node:
            if isinstance(value, Mapping) or _is_sequence(value):
                child = _safe_node(value, parent_key)
                if child not in ({}, [], None):
                    safe_items.append(child)
            elif parent_is_allowed and not _unsafe_scalar(parent_key, value):
                safe_items.append(value)
        return safe_items
    return node


def _normalize_key(key: str) -> str:
    return key.strip().replace("-", "_").casefold()


def _join_key(parent_key: str, key: str) -> str:
    return f"{parent_key}.{key}" if parent_key else key


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_allowed_restricted(key: str) -> bool:
    normalized = _normalize_key(key)
    leaf = normalized.rsplit(".", 1)[-1]
    return normalized in _ALLOWED_RESTRICTED_KEYS or leaf in _ALLOWED_RESTRICTED_KEYS


def _unsafe_scalar(key: str, value: object) -> bool:
    if _normalize_key(key).rsplit(".", 1)[-1] == "reason_code":
        return not isinstance(value, str) or value not in _APPROVED_REASON_CODES
    if not isinstance(value, str):
        return False
    if "@" in value:
        return True
    return (
        _normalize_key(key).rsplit(".", 1)[-1] == "message" and value not in _ALLOWED_LOG_MESSAGES
    )
