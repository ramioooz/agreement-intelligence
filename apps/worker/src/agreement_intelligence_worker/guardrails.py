"""Deterministic boundaries for uploaded and retrieved untrusted evidence."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agreement_intelligence_platform.privacy import safe_event_metadata
from opentelemetry.trace import Span, get_current_span

_POLICY_VERSION = "untrusted-evidence.v1"
_INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:forget|ignore|disregard|override)\b.{0,48}"
    r"\b(?:instructions?|rules?|system|developer|message)\b",
    re.IGNORECASE | re.DOTALL,
)
_PROMPT_EXFILTRATION = re.compile(
    r"\b(?:reveal|show|print|expose|output)\b.{0,48}"
    r"\b(?:system|developer|hidden|prompt|instruction)\b",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_OR_WRITE_ACTION = re.compile(
    r"(?:^|(?<=[.!?]))\s*(?:please\s+)?(?:"
    r"(?:use|call|invoke|run|execute)\b.{0,32}\b(?:tool|function|mcp|api)\b"
    r"|(?:delete|write|update|upload|send)\b.{0,32}"
    r"\b(?:file|database|record|agreement|external|http)\b"
    r"|(?:email|send)\b.{0,48}\b(?:confidential\s+clauses?|complete\s+document)\b"
    r")",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)
_BASE64_TOKEN = re.compile(
    r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{8,4096}(?:={1,2})?(?![A-Za-z0-9+/_=-])"
)
_HEX_TOKEN = re.compile(r"\b(?:[0-9a-fA-F]{2}){8,2048}\b")
_BASE64_DATA_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/_-"
)
_MAX_DECODE_DEPTH = 2
_MAX_DECODE_CANDIDATES = 8
_MAX_DECODE_CHARACTERS = 4_096


@dataclass(frozen=True)
class GuardrailDecision:
    status: Literal["allow", "review", "block"]
    reason_codes: tuple[str, ...]
    policy_version: str = _POLICY_VERSION

    def provenance(self) -> dict[str, object]:
        """Return only safe, versioned decision metadata for persistence or spans."""

        return {
            "policy_version": self.policy_version,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
        }


def record_guardrail_span_provenance(
    decision: GuardrailDecision, *, span: Span | None = None
) -> None:
    """Attach only privacy-approved decision metadata to an evaluated span."""

    safe_attributes = safe_event_metadata(
        {
            "guardrail_policy_version": decision.policy_version,
            "guardrail_status": decision.status,
            "guardrail_reason_codes": list(decision.reason_codes),
        }
    )
    target = get_current_span() if span is None else span
    policy_version = safe_attributes.get("guardrail_policy_version")
    status = safe_attributes.get("guardrail_status")
    reason_codes = safe_attributes.get("guardrail_reason_codes")
    if isinstance(policy_version, str):
        target.set_attribute("guardrail.policy_version", policy_version)
    if isinstance(status, str):
        target.set_attribute("guardrail.status", status)
    if isinstance(reason_codes, list):
        safe_reason_codes = [reason for reason in reason_codes if isinstance(reason, str)]
        if len(safe_reason_codes) == len(reason_codes):
            target.set_attribute("guardrail.reason_codes", safe_reason_codes)
    elif not decision.reason_codes:
        target.set_attribute("guardrail.reason_codes", [])


def validate_untrusted_evidence(
    evidence: Sequence[tuple[str, str]], allowed_anchor_ids: Sequence[str] | set[str]
) -> GuardrailDecision:
    """Classify evidence without granting access, changing scope, or executing content."""

    allowed = set(allowed_anchor_ids)
    reason_codes: list[str] = []
    for anchor_id, text in evidence:
        if anchor_id not in allowed:
            _add_reason(reason_codes, "unknown_anchor_id")
        if _PROMPT_EXFILTRATION.search(text):
            _add_reason(reason_codes, "prompt_exfiltration_request")
        elif _TOOL_OR_WRITE_ACTION.search(text):
            _add_reason(reason_codes, "tool_or_write_action_request")
        elif _INSTRUCTION_OVERRIDE.search(text):
            _add_reason(reason_codes, "instruction_override_marker")
        if any(
            _is_prohibited_decoded_request(candidate)
            for candidate in _decoded_text_candidates(text)
        ):
            _add_reason(reason_codes, "encoded_exfiltration_request")

    block_reasons = {
        "unknown_anchor_id",
        "prompt_exfiltration_request",
        "encoded_exfiltration_request",
        "tool_or_write_action_request",
    }
    status: Literal["allow", "review", "block"]
    if any(reason in block_reasons for reason in reason_codes):
        status = "block"
    elif reason_codes:
        status = "review"
    else:
        status = "allow"
    return GuardrailDecision(status=status, reason_codes=tuple(reason_codes))


def _decoded_text_candidates(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    pending = [text[:_MAX_DECODE_CHARACTERS]]
    for _ in range(_MAX_DECODE_DEPTH):
        next_pending: list[str] = []
        for value in pending:
            tokens = (
                *_BASE64_TOKEN.findall(value),
                *_fragmented_base64_tokens(value),
                *_HEX_TOKEN.findall(value),
            )
            for token in tokens:
                decoded = _decode_token(token)
                if decoded is not None and decoded not in candidates:
                    candidates.append(decoded)
                    next_pending.append(decoded)
                    if len(candidates) >= _MAX_DECODE_CANDIDATES:
                        return tuple(candidates + ["__decode_candidate_cap__"])
        pending = next_pending
        if not pending:
            break
    return tuple(candidates)


def _decode_token(token: str) -> str | None:
    try:
        if _HEX_TOKEN.fullmatch(token):
            decoded = bytes.fromhex(token)
        else:
            padded = token + "=" * (-len(token) % 4)
            decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = decoded.decode("utf-8")
    except (UnicodeDecodeError, ValueError, binascii.Error):
        return None
    return value if value.isprintable() and len(value) <= _MAX_DECODE_CHARACTERS else None


def _fragmented_base64_tokens(value: str) -> tuple[str, ...]:
    """Join bounded Base64 fragments separated only by whitespace."""

    tokens: list[str] = []
    fragments: list[str] = []
    current: list[str] = []

    def finish_fragment() -> None:
        if current:
            fragments.append("".join(current))
            current.clear()

    def finish_sequence() -> None:
        finish_fragment()
        if len(fragments) > 1:
            candidate = "".join(fragments)
            data = candidate.rstrip("=")
            padding = candidate[len(data) :]
            if (
                8 <= len(data) <= _MAX_DECODE_CHARACTERS
                and len(data) % 4 != 1
                and padding in {"", "=", "=="}
                and "=" not in data
            ):
                tokens.append(candidate)
        fragments.clear()

    for character in value[:_MAX_DECODE_CHARACTERS]:
        if character in _BASE64_DATA_CHARACTERS or character == "=":
            current.append(character)
        elif character in " \t\r\n":
            finish_fragment()
        else:
            finish_sequence()
    finish_sequence()
    return tuple(tokens)


def _is_prohibited_decoded_request(text: str) -> bool:
    if text == "__decode_candidate_cap__":
        return True
    return bool(
        _PROMPT_EXFILTRATION.search(text)
        or _TOOL_OR_WRITE_ACTION.search(text)
        or _INSTRUCTION_OVERRIDE.search(text)
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)
