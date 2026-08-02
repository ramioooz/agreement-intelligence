import asyncio
import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import agreement_intelligence_api.playbooks.models  # noqa: F401
import pytest
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.documents.storage import DocumentStorage, StoredDocument
from agreement_intelligence_api.identity.authz import Principal
from agreement_intelligence_api.identity.models import Base, Organization, Workspace
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.processing.models import (
    ProcessingArtifactRecord,
    ProcessingJobRecord,
)
from agreement_intelligence_api.reviews.models import (
    PlaybookEvaluationRecord,
    PlaybookFindingRecord,
)
from agreement_intelligence_mcp.app import create_server
from agreement_intelligence_mcp.auth import OidcBearerTokenVerifier
from agreement_intelligence_mcp.models import McpAuditEventRecord
from agreement_intelligence_mcp.service import (
    McpReadService,
    ResourceNotFoundError,
    ToolCallContext,
)
from fastapi import HTTPException
from opentelemetry import trace
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


class MemoryStorage:
    def __init__(self, documents: dict[str, StoredDocument]) -> None:
        self.documents = documents

    def read(self, key: str) -> StoredDocument | None:
        return self.documents.get(key)


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    database_session = sessionmaker(bind=engine)()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def _scope(
    session: Session, *, role: RoleKey = RoleKey.LEGAL_REVIEWER
) -> tuple[Principal, Organization, Workspace]:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    user = identity.provision_user(
        issuer="https://identity.example/realms/demo",
        subject=f"user-{uuid4()}",
        display_name="MCP User",
    )
    organization = identity.create_organization(name=f"Acme {uuid4()}", slug=f"acme-{uuid4()}")
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Legal",
        slug=f"legal-{uuid4()}",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=role,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    session.commit()
    return Principal(user_id=user.id), organization, workspace


def _agreement(session: Session, organization: Organization, workspace: Workspace) -> UUID:
    agreement_id = uuid4()
    now = datetime.now(UTC)
    session.add(
        AgreementRecord(
            id=agreement_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            title="Master Services Agreement",
            agreement_type="services",
            status="active",
            parties=[],
            files=[],
            processing_state="completed",
            audit_metadata={},
            audit_events=[],
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    return agreement_id


def _context(tool_name: str, traceparent: str | None = None) -> ToolCallContext:
    headers = {"traceparent": traceparent} if traceparent is not None else {}
    return ToolCallContext.from_headers(tool_name, headers)


def test_invalid_token_is_rejected_by_the_oidc_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_: str) -> Principal:
        raise HTTPException(status_code=401, detail={"code": "authentication_required"})

    monkeypatch.setattr("agreement_intelligence_mcp.auth.authenticate_access_token", reject)

    assert asyncio.run(OidcBearerTokenVerifier().verify_token("not-a-token")) is None


def test_sdk_server_exposes_only_the_read_only_tools() -> None:
    server = create_server(
        cast(Callable[[], Session], lambda: None),
        cast(Callable[[], DocumentStorage], lambda: MemoryStorage({})),
    )

    assert {tool.name for tool in asyncio.run(server.list_tools())} == {
        "search_agreements",
        "get_citation",
        "get_agreement_status",
        "get_review_status",
    }


def test_search_returns_no_results_with_an_immutable_audit_event(session: Session) -> None:
    principal, organization, workspace = _scope(session)
    service = McpReadService(session, MemoryStorage({}))

    result = service.search_agreements(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        query="absent",
        limit=10,
        context=_context("search_agreements"),
    )

    assert result == {"items": [], "next_cursor": None}
    event = session.scalar(select(McpAuditEventRecord))
    assert event is not None
    assert event.tool_name == "search_agreements"
    assert event.outcome == "success"


def test_cross_tenant_scope_is_hidden(session: Session) -> None:
    principal, _, _ = _scope(session)
    _, other_organization, other_workspace = _scope(session)
    service = McpReadService(session, MemoryStorage({}))

    with pytest.raises(ResourceNotFoundError):
        service.search_agreements(
            principal,
            organization_id=other_organization.id,
            workspace_id=other_workspace.id,
            query="services",
            limit=10,
            context=_context("search_agreements"),
        )


def test_unapproved_workspace_agreement_is_hidden(session: Session) -> None:
    principal, organization, allowed_workspace = _scope(session)
    hidden_workspace = IdentityService(session).create_workspace(
        organization_id=organization.id,
        name="Restricted",
        slug=f"restricted-{uuid4()}",
    )
    agreement_id = _agreement(session, organization, hidden_workspace)
    service = McpReadService(session, MemoryStorage({}))

    with pytest.raises(ResourceNotFoundError):
        service.get_agreement_status(
            principal,
            organization_id=organization.id,
            workspace_id=allowed_workspace.id,
            agreement_id=agreement_id,
            context=_context("get_agreement_status"),
        )


def test_citation_returns_only_the_requested_cited_excerpt(session: Session) -> None:
    principal, organization, workspace = _scope(session)
    agreement_id = _agreement(session, organization, workspace)
    artifact_key = "analysis/contract.json"
    now = datetime.now(UTC)
    job_id = uuid4()
    session.add(
        ProcessingJobRecord(
            id=job_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            idempotency_key="mcp-citation",
            profile="baseline",
            source_storage_key=None,
            source_checksum=None,
            source_content_type=None,
            state="completed",
            attempt_count=1,
            queued_at=now,
            processing_started_at=now,
            completed_at=now,
        )
    )
    session.add(
        ProcessingArtifactRecord(
            job_id=job_id, agreement_id=agreement_id, artifact_key=artifact_key
        )
    )
    session.commit()
    citation_text = "Either party may terminate with thirty days notice."
    storage = MemoryStorage(
        {
            artifact_key: StoredDocument(
                content=json.dumps(
                    {
                        "document": {
                            "pages": [
                                {
                                    "number": 3,
                                    "blocks": [
                                        {
                                            "anchor_id": "citation-termination",
                                            "text": citation_text,
                                        }
                                    ],
                                }
                            ]
                        },
                        "citations": [
                            {
                                "anchor_id": "citation-termination",
                                "page_number": 3,
                                "block_index": 0,
                            }
                        ],
                    }
                ).encode(),
                content_type="application/json",
            )
        }
    )

    result = McpReadService(session, storage).get_citation(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement_id,
        citation_id="citation-termination",
        context=_context("get_citation"),
    )

    assert result == {
        "citation_id": "citation-termination",
        "page_number": 3,
        "excerpt": citation_text,
    }


def test_review_status_is_scoped_to_the_agreement(session: Session) -> None:
    principal, organization, workspace = _scope(session)
    agreement_id = _agreement(session, organization, workspace)
    evaluation_id = uuid4()
    session.add(
        PlaybookEvaluationRecord(
            id=evaluation_id,
            organization_id=organization.id,
            workspace_id=workspace.id,
            agreement_id=agreement_id,
            processing_job_id=None,
            playbook_version_id=uuid4(),
            analysis_version="analysis.v1",
            extraction_version="extraction.v1",
            state="completed",
            requested_by=principal.user_id,
        )
    )
    session.add(
        PlaybookFindingRecord(
            id=uuid4(),
            organization_id=organization.id,
            workspace_id=workspace.id,
            evaluation_id=evaluation_id,
            rule_id=uuid4(),
            result="needs_review",
            severity="high",
            confidence=0.8,
            method="deterministic",
            citation_ids=["citation-termination"],
            extraction_version="extraction.v1",
            review_state="unreviewed",
            risk_payload={},
            fallback_suggestions=[],
        )
    )
    session.commit()

    result = McpReadService(session, MemoryStorage({})).get_review_status(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement_id,
        context=_context("get_review_status"),
    )

    assert result == {
        "state": "completed",
        "findings": {"needs_review": 1},
        "review_state": "unreviewed",
    }


def test_traceparent_is_propagated_to_the_audit_event(session: Session) -> None:
    principal, organization, workspace = _scope(session)
    service = McpReadService(session, MemoryStorage({}))
    trace_id = "0af7651916cd43dd8448eb211c80319c"

    service.search_agreements(
        principal,
        organization_id=organization.id,
        workspace_id=workspace.id,
        query="services",
        limit=10,
        context=_context("search_agreements", f"00-{trace_id}-b7ad6b7169203331-01"),
    )

    event = session.scalar(select(McpAuditEventRecord))
    assert event is not None
    assert event.trace_id == trace_id
    assert trace.get_current_span().get_span_context().is_valid is False
