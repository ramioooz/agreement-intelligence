import { describe, expect, it, vi } from "vitest";

import { refreshKeycloakToken } from "@/lib/keycloak-token";

describe("refreshKeycloakToken", () => {
  it("uses the refresh grant to replace an expired access token", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "renewed-access-token",
          expires_in: 300,
          id_token: "renewed-id-token",
          refresh_token: "rotated-refresh-token",
        }),
        { status: 200 },
      ),
    );

    const token = await refreshKeycloakToken(
      {
        keycloakAccessToken: "expired-access-token",
        keycloakRefreshToken: "refresh-token",
        keycloakAccessTokenExpiresAt: 1,
      },
      {
        clientId: "agreement-intelligence-web",
        clientSecret: "client-secret",
        issuer: "http://keycloak:8080/realms/agreement-intelligence",
        fetcher,
        now: 10_000,
      },
    );

    expect(fetcher).toHaveBeenCalledWith(
      "http://keycloak:8080/realms/agreement-intelligence/protocol/openid-connect/token",
      expect.objectContaining({ method: "POST" }),
    );
    expect(token).toMatchObject({
      keycloakAccessToken: "renewed-access-token",
      keycloakIdToken: "renewed-id-token",
      keycloakRefreshToken: "rotated-refresh-token",
      keycloakAccessTokenExpiresAt: 310_000,
    });
  });
});
