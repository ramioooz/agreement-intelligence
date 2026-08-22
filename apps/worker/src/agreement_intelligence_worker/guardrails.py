"""Deterministic boundaries for uploaded and retrieved untrusted evidence."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_POLICY_VERSION = "untrusted-evidence.v1"
_INSTRUCTION_OVERRIDE = re.compile(
    r"\b(?:ignore|disregard|override)\b.{0,48}\b(?:instructions?|system|developer|message)\b",
    re.IGNORECASE | re.DOTALL,
)
_PROMPT_EXFILTRATION = re.compile(
    r"\b(?:reveal|show|print|expose)\b.{0,48}\b(?:system|developer|hidden|prompt|instruction)\b",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_OR_WRITE_ACTION = re.compile(
    r"\b(?:use|call|invoke|run|execute)\b.{0,32}\b(?:tool|function|mcp|api)\b"
    r"|\b(?:delete|write|update|upload|send)\b.{0,32}\b(?:file|database|record|agreement|external|http)\b",
    re.IGNORECASE | re.DOTALL,
)
_BASE64_TOKEN = re.compile(r"\b(?:[A-Za-z0-9+/]{4})+(?:={0,2})\b")


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
    for token in _BASE64_TOKEN.findall(text):
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except (UnicodeDecodeError, binascii.Error):
            continue
        if decoded.isprintable():
            candidates.append(decoded)
    return tuple(candidates)


def _is_prohibited_decoded_request(text: str) -> bool:
    return bool(
        _PROMPT_EXFILTRATION.search(text)
        or _TOOL_OR_WRITE_ACTION.search(text)
        or _INSTRUCTION_OVERRIDE.search(text)
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)
