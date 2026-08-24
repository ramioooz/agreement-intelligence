from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from agreement_intelligence_api.audit.models import AuditEventRecord
from agreement_intelligence_api.audit.schemas import AuditEventResponse
from agreement_intelligence_api.correlation import get_correlation_id
from agreement_intelligence_api.identity.authz import Principal, hide_resource
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService

_REDACTED = "[REDACTED]"
_MAX_SAFE_TEXT_LENGTH = 256
_SENSITIVE_KEY_FRAGMENTS = (
    "agreement_text",
    "document_text",
    "source_text",
    "raw_text",
    "content",
    "prompt",
    "completion",
    "provider_output",
    "secret",
    "token",
    "password",
    "credential",
    "api_key",
    "authorization",
)
_FREE_FORM_KEY_FRAGMENTS = (
    "reason",
    "note",
    "comment",
    "rationale",
    "explanation",
    "description",
    "message",
    "body",
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
_CREDENTIAL_PATTERN = re.compile(
    r"(?:\b(?:sk|pk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----)",
    re.IGNORECASE,
)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d(?:[\s().-]*\d){7,}(?!\w)")
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_RESTRICTED_TEXT_PATTERN = re.compile(
    r"(?:\bthis\s+(?:agreement|contract)\b|\bwhereas\b|\bgoverning\s+law\b|"
    r"\bterms\s+and\s+conditions\b|\b(?:the\s+)?(?:supplier|customer|party|parties)\s+"
    r"shall\b|\bthe\s+parties\s+agree\s+(?:to|that)\b|\b(?:ignore|disregard|override)\s+"
    r"(?:all\s+)?(?:previous|prior|earlier)\s+"
    r"(?:instructions?|directions?)\b|\bhidden\s+instructions?\b|\bsystem\s+prompt\b|"
    r"\bprovider\s+(?:output|response)\b|\b(?:here\s+is\s+)?(?:the\s+)?assistant\s+"
    r"(?:output|response)\b|\bmodel\s+(?:output|response|completion)\b)",
    re.IGNORECASE,
)


class AuditEventWriter:
    """Write safe state-transition records without owning transaction boundaries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        outcome: str,
        correlation_id: str | None = None,
        before_ref: Mapping[str, object] | None = None,
        after_ref: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEventRecord:
        event = AuditEventRecord(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            correlation_id=correlation_id or get_correlation_id(),
            before_ref=_safe_mapping(before_ref),
            after_ref=_safe_mapping(after_ref),
            metadata_json=_safe_mapping(metadata),
            occurred_at=occurred_at or datetime.now(UTC),
        )
        self._session.add(event)
        return event


class AuditLedgerService:
    def __init__(self, session: Session, identity: IdentityService) -> None:
        self._session = session
        self._identity = identity

    def list_events(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        resource_type: str | None,
        resource_id: UUID | None,
        limit: int,
    ) -> list[AuditEventResponse]:
        if not self._identity.can_access_workspace(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            permission=PermissionKey.AUDIT_READ,
        ):
            hide_resource()
        statement = (
            select(AuditEventRecord)
            .where(AuditEventRecord.organization_id == organization_id)
            .where(AuditEventRecord.workspace_id == workspace_id)
            .order_by(desc(AuditEventRecord.occurred_at), desc(AuditEventRecord.id))
            .limit(limit)
        )
        if resource_type is not None:
            statement = statement.where(AuditEventRecord.resource_type == resource_type)
        if resource_id is not None:
            statement = statement.where(AuditEventRecord.resource_id == resource_id)
        return [_response(event) for event in self._session.scalars(statement)]


def _response(event: AuditEventRecord) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        organization_id=event.organization_id,
        workspace_id=event.workspace_id,
        actor_id=event.actor_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        outcome=event.outcome,
        correlation_id=event.correlation_id,
        before_ref=event.before_ref,
        after_ref=event.after_ref,
        metadata=event.metadata_json,
        occurred_at=event.occurred_at,
    )


def _safe_mapping(value: Mapping[str, object] | None) -> dict[str, Any]:
    return {str(key): _safe_value(str(key), item) for key, item in (value or {}).items()}


def _safe_value(key: str, value: object) -> Any:
    if _is_reason_code_key(key):
        return value if isinstance(value, str) and value in _APPROVED_REASON_CODES else _REDACTED
    if _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, str):
        return _REDACTED if _is_restricted_text(value) else value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _REDACTED


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS) or any(
        fragment in normalized for fragment in _FREE_FORM_KEY_FRAGMENTS
    )


def _is_reason_code_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return normalized == "reason_code" or normalized.endswith("_reason_code")


def _is_restricted_text(value: str) -> bool:
    return _UUID_PATTERN.fullmatch(value) is None and (
        len(value) > _MAX_SAFE_TEXT_LENGTH
        or _CREDENTIAL_PATTERN.search(value) is not None
        or _JWT_PATTERN.search(value) is not None
        or _EMAIL_PATTERN.search(value) is not None
        or _PHONE_PATTERN.search(value) is not None
        or _RESTRICTED_TEXT_PATTERN.search(value) is not None
    )
