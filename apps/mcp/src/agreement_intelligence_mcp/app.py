from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from agreement_intelligence_api.db import engine
from agreement_intelligence_api.documents.storage import DocumentStorage, storage_from_environment
from agreement_intelligence_api.identity.authz import Principal, authenticate_access_token
from agreement_intelligence_platform.privacy import safe_event_metadata
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.context import Context
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session, sessionmaker

from agreement_intelligence_mcp import __version__
from agreement_intelligence_mcp.auth import OidcBearerTokenVerifier
from agreement_intelligence_mcp.service import McpReadService, ToolCallContext

SessionFactory = Callable[[], Session]
StorageFactory = Callable[[], DocumentStorage]


def create_server(
    session_factory: SessionFactory,
    storage_factory: StorageFactory,
) -> MCPServer:
    """Build the restricted remote MCP server using Streamable HTTP transport."""
    server = MCPServer(
        name="Agreement Intelligence",
        version=__version__,
        instructions=(
            "Read-only agreement intelligence. Every request must include organization and "
            "workspace scope. Citation retrieval returns only the requested cited excerpt."
        ),
        token_verifier=OidcBearerTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(
                os.environ.get("OIDC_ISSUER", "http://localhost:8080/realms/agreement-intelligence")
            ),
            resource_server_url=AnyHttpUrl(
                os.environ.get("MCP_PUBLIC_URL", "http://localhost:8001/mcp")
            ),
            required_scopes=["mcp:read"],
        ),
    )

    @server.tool()
    def search_agreements(
        organization_id: UUID,
        workspace_id: UUID,
        query: str,
        ctx: Context,
        limit: int = 10,
    ) -> dict[str, object]:
        """Find agreement metadata inside an authorized organization and workspace."""
        return _call(
            ctx,
            "search_agreements",
            session_factory,
            storage_factory,
            lambda service, principal, context: service.search_agreements(
                principal,
                organization_id=organization_id,
                workspace_id=workspace_id,
                query=query,
                limit=limit,
                context=context,
            ),
        )

    @server.tool()
    def get_citation(
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        citation_id: str,
        ctx: Context,
    ) -> dict[str, object]:
        """Retrieve one cited excerpt from an authorized agreement analysis artifact."""
        return _call(
            ctx,
            "get_citation",
            session_factory,
            storage_factory,
            lambda service, principal, context: service.get_citation(
                principal,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=agreement_id,
                citation_id=citation_id,
                context=context,
            ),
        )

    @server.tool()
    def get_agreement_status(
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        ctx: Context,
    ) -> dict[str, object]:
        """Retrieve lifecycle and processing status for one authorized agreement."""
        return _call(
            ctx,
            "get_agreement_status",
            session_factory,
            storage_factory,
            lambda service, principal, context: service.get_agreement_status(
                principal,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=agreement_id,
                context=context,
            ),
        )

    @server.tool()
    def get_review_status(
        organization_id: UUID,
        workspace_id: UUID,
        agreement_id: UUID,
        ctx: Context,
    ) -> dict[str, object]:
        """Retrieve aggregate review status for one authorized agreement."""
        return _call(
            ctx,
            "get_review_status",
            session_factory,
            storage_factory,
            lambda service, principal, context: service.get_review_status(
                principal,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agreement_id=agreement_id,
                context=context,
            ),
        )

    return server


def create_app() -> Any:
    server = create_server(_new_session, storage_from_environment)
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
    )


def _call(
    ctx: Context,
    tool_name: str,
    session_factory: SessionFactory,
    storage_factory: StorageFactory,
    operation: Callable[[McpReadService, Principal, ToolCallContext], dict[str, object]],
) -> dict[str, object]:
    headers = ctx.headers or {}
    principal = _principal_from_headers(headers)
    session = session_factory()
    try:
        return operation(
            McpReadService(session, storage_factory()),
            principal,
            ToolCallContext.from_headers(tool_name, _safe_context_headers(headers)),
        )
    finally:
        session.close()


def _principal_from_headers(headers: Mapping[str, str]) -> Principal:
    authorization = headers.get("authorization") or headers.get("Authorization")
    if authorization is None or not authorization.startswith("Bearer "):
        raise PermissionError("bearer authentication is required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise PermissionError("bearer authentication is required")
    return authenticate_access_token(token)


def _safe_context_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value for key, value in safe_event_metadata(headers).items() if isinstance(value, str)
    }


def _new_session() -> Session:
    return sessionmaker(bind=engine())()


app = create_app()
