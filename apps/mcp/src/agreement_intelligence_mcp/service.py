from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agreement_intelligence_api.agreements.access import active_agreement_statement
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.documents.storage import StoredDocument
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.permissions import PermissionKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.mcp_audit import McpAuditEventRecord
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from agreement_intelligence_api.reviews.models import (
    PlaybookEvaluationRecord,
    PlaybookFindingRecord,
)
from agreement_intelligence_platform.privacy import safe_event_metadata
from agreement_intelligence_worker.guardrails import (
    record_guardrail_span_provenance,
    validate_untrusted_evidence,
)
from opentelemetry.context.context import Context as OtelContext
from opentelemetry.propagate import extract
from opentelemetry.trace import Span, get_current_span, get_tracer
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

_MAX_CITATION_EXCERPT_CHARACTERS = 2_000
_tracer = get_tracer("agreement_intelligence.mcp")


class ArtifactStorage(Protocol):
    def read(self, key: str) -> StoredDocument | None: ...


class ResourceNotFoundError(Exception):
    """A resource-agnostic failure that avoids disclosure across tenant scopes."""


@dataclass(frozen=True)
class ToolCallContext:
    tool_name: str
    parent_context: OtelContext

    @classmethod
    def from_headers(cls, tool_name: str, headers: Mapping[str, str]) -> ToolCallContext:
        return cls(tool_name=tool_name, parent_context=extract(dict(headers)))


class McpReadService:
    """Scoped data access for the MCP tool surface.

    The service intentionally offers no generic queries, document downloads, or
    mutations. Every public method requires the API organization/workspace
    scope and writes one audit event for the attempt.
    """

    def __init__(self, session: Session, storage: ArtifactStorage) -> None:
        self._session = session
        self._storage = storage
        self._identity = IdentityService(session)

    def search_agreements(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        query: str,
        limit: int,
        context: ToolCallContext,
    ) -> dict[str, object]:
        if not query.strip() or len(query) > 500 or not 1 <= limit <= 25:
            raise ValueError("query and limit are outside the allowed bounds")
        with self._audit_scope(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=None,
            context=context,
            attributes={"query_present": True, "limit": limit},
        ):
            agreements = list(
                self._session.scalars(
                    select(AgreementRecord)
                    .where(AgreementRecord.organization_id == organization_id)
                    .where(AgreementRecord.workspace_id == workspace_id)
                    .where(AgreementRecord.archived_at.is_(None))
                    .where(AgreementRecord.deletion_requested_at.is_(None))
                    .where(AgreementRecord.title.ilike(f"%{query.strip()}%"))
                    .order_by(AgreementRecord.created_at, AgreementRecord.id)
                    .limit(limit)
                )
            )
            return {
                "items": [
                    {
                        "agreement_id": str(agreement.id),
                        "title": agreement.title,
                        "agreement_type": agreement.agreement_type,
                        "status": agreement.status,
                        "processing_state": agreement.processing_state,
                    }
                    for agreement in agreements
                ],
                "next_cursor": None,
            }

    def get_agreement_status(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        context: ToolCallContext,
    ) -> dict[str, object]:
        with self._audit_scope(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            context=context,
            attributes={},
        ):
            agreement = self._agreement(agreement_id, organization_id, workspace_id)
            return {
                "status": agreement.status,
                "processing_state": agreement.processing_state,
                "archived": agreement.archived_at is not None,
                "updated_at": agreement.updated_at.isoformat(),
            }

    def get_citation(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        citation_id: str,
        context: ToolCallContext,
    ) -> dict[str, object]:
        if not citation_id.startswith("citation-") or len(citation_id) > 128:
            raise ValueError("citation_id is invalid")
        audit_attributes: dict[str, object] = {"citation_id": citation_id}
        with self._audit_scope(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            context=context,
            attributes=audit_attributes,
        ) as span:
            self._agreement(agreement_id, organization_id, workspace_id)
            artifact_key = self._completed_artifact_key(agreement_id, organization_id, workspace_id)
            document = self._storage.read(artifact_key) if artifact_key else None
            citation = _citation_from_artifact(document, citation_id)
            if citation is None:
                raise ResourceNotFoundError
            decision = validate_untrusted_evidence(
                [(citation_id, str(citation["excerpt"]))], {citation_id}
            )
            record_guardrail_span_provenance(decision, span=span)
            audit_attributes.update(
                {
                    "guardrail_policy_version": decision.policy_version,
                    "guardrail_status": decision.status,
                    "guardrail_reason_codes": list(decision.reason_codes),
                }
            )
            if decision.status != "allow":
                raise ResourceNotFoundError
            return citation

    def get_review_status(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        context: ToolCallContext,
    ) -> dict[str, object]:
        with self._audit_scope(
            principal,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agreement_id=agreement_id,
            context=context,
            attributes={},
        ):
            self._agreement(agreement_id, organization_id, workspace_id)
            evaluation = self._session.scalar(
                select(PlaybookEvaluationRecord)
                .where(PlaybookEvaluationRecord.organization_id == organization_id)
                .where(PlaybookEvaluationRecord.workspace_id == workspace_id)
                .where(PlaybookEvaluationRecord.agreement_id == agreement_id)
                .order_by(desc(PlaybookEvaluationRecord.created_at), PlaybookEvaluationRecord.id)
            )
            if evaluation is None:
                return {"state": "not_started", "findings": {}, "review_state": "not_started"}
            findings = list(
                self._session.scalars(
                    select(PlaybookFindingRecord)
                    .where(PlaybookFindingRecord.organization_id == organization_id)
                    .where(PlaybookFindingRecord.workspace_id == workspace_id)
                    .where(PlaybookFindingRecord.evaluation_id == evaluation.id)
                )
            )
            states = {finding.review_state for finding in findings}
            review_state = (
                "not_started" if not states else next(iter(states)) if len(states) == 1 else "mixed"
            )
            return {
                "state": evaluation.state,
                "findings": dict(Counter(finding.result for finding in findings)),
                "review_state": review_state,
            }

    @contextmanager
    def _audit_scope(
        self,
        principal: Principal,
        *,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID | None,
        context: ToolCallContext,
        attributes: dict[str, object],
    ) -> Iterator[Span]:
        with _tracer.start_as_current_span(
            f"mcp.tool.{context.tool_name}", context=context.parent_context
        ) as span:
            span_context = span.get_span_context()
            if not span_context.is_valid:
                span_context = get_current_span(context.parent_context).get_span_context()
            try:
                self._authorize(principal, organization_id, workspace_id)
                yield span
            except (ResourceNotFoundError, ValueError):
                self._record_audit(
                    principal,
                    organization_id,
                    workspace_id,
                    agreement_id,
                    context.tool_name,
                    "not_found",
                    attributes,
                    span_context.trace_id,
                    span_context.span_id,
                )
                raise
            except Exception:
                self._record_audit(
                    principal,
                    organization_id,
                    workspace_id,
                    agreement_id,
                    context.tool_name,
                    "error",
                    attributes,
                    span_context.trace_id,
                    span_context.span_id,
                )
                raise
            else:
                self._record_audit(
                    principal,
                    organization_id,
                    workspace_id,
                    agreement_id,
                    context.tool_name,
                    "success",
                    attributes,
                    span_context.trace_id,
                    span_context.span_id,
                )

    def _authorize(self, principal: Principal, organization_id: UUID, workspace_id: UUID) -> None:
        for permission in (PermissionKey.AGREEMENTS_READ, PermissionKey.SEARCH_QUERY):
            if not self._identity.can_access_workspace(
                principal,
                organization_id=organization_id,
                workspace_id=workspace_id,
                permission=permission,
            ):
                raise ResourceNotFoundError

    def _agreement(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> AgreementRecord:
        agreement = self._session.scalar(
            active_agreement_statement(
                agreement_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        )
        if agreement is None:
            raise ResourceNotFoundError
        return agreement

    def _completed_artifact_key(
        self, agreement_id: UUID, organization_id: UUID, workspace_id: UUID
    ) -> str | None:
        return self._session.scalar(
            select(ProcessingArtifactRecord.artifact_key)
            .join(ProcessingJobRecord, ProcessingArtifactRecord.job_id == ProcessingJobRecord.id)
            .where(ProcessingArtifactRecord.agreement_id == agreement_id)
            .where(ProcessingJobRecord.organization_id == organization_id)
            .where(ProcessingJobRecord.workspace_id == workspace_id)
            .where(ProcessingJobRecord.state == "completed")
            .order_by(desc(ProcessingArtifactRecord.created_at))
            .limit(1)
        )

    def _record_audit(
        self,
        principal: Principal,
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID | None,
        tool_name: str,
        outcome: str,
        attributes: dict[str, object],
        trace_id: int,
        span_id: int,
    ) -> None:
        self._session.add(
            McpAuditEventRecord(
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=agreement_id,
                actor_id=principal.user_id,
                tool_name=tool_name,
                outcome=outcome,
                trace_id=f"{trace_id:032x}" if trace_id else None,
                span_id=f"{span_id:016x}" if span_id else None,
                attributes=safe_event_metadata(attributes),
            )
        )
        self._session.commit()


def _citation_from_artifact(
    stored: StoredDocument | None, citation_id: str
) -> dict[str, object] | None:
    if stored is None or stored.content_type != "application/json":
        return None
    try:
        artifact = json.loads(stored.content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(artifact, dict):
        return None
    citations = artifact.get("citations")
    document = artifact.get("document")
    if not isinstance(citations, list) or not isinstance(document, dict):
        return None
    citation = next(
        (
            item
            for item in citations
            if isinstance(item, dict) and item.get("anchor_id") == citation_id
        ),
        None,
    )
    if citation is None or not isinstance(citation.get("page_number"), int):
        return None
    pages = document.get("pages")
    if not isinstance(pages, list):
        return None
    for page in pages:
        if not isinstance(page, dict) or page.get("number") != citation["page_number"]:
            continue
        blocks = page.get("blocks")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get("anchor_id") != citation_id:
                continue
            text = block.get("text")
            if isinstance(text, str):
                return {
                    "citation_id": citation_id,
                    "page_number": citation["page_number"],
                    "excerpt": text[:_MAX_CITATION_EXCERPT_CHARACTERS],
                }
    return None
