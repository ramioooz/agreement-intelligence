from __future__ import annotations

from agreement_intelligence_api.identity.authz import authenticate_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier


class OidcBearerTokenVerifier(TokenVerifier):
    """MCP SDK verifier backed by the API's fail-closed OIDC validation."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = authenticate_access_token(token)
        except Exception:
            return None
        return AccessToken(
            token=token,
            client_id="agreement-intelligence-mcp",
            scopes=["mcp:read"],
            subject=str(principal.user_id),
        )
