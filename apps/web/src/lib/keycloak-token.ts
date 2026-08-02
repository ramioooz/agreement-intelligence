export type KeycloakSessionToken = {
  keycloakAccessToken?: string;
  keycloakAccessTokenExpiresAt?: number;
  keycloakIdToken?: string;
  keycloakRefreshError?: "refresh_failed";
  keycloakRefreshToken?: string;
};

type RefreshOptions = {
  clientId: string;
  clientSecret: string;
  fetcher?: typeof fetch;
  issuer: string;
  now?: number;
};

type RefreshResponse = {
  access_token?: string;
  expires_in?: number;
  id_token?: string;
  refresh_token?: string;
};

export function hasUsableKeycloakAccessToken(
  token: KeycloakSessionToken,
  now = Date.now(),
): boolean {
  return (
    typeof token.keycloakAccessToken === "string" &&
    typeof token.keycloakAccessTokenExpiresAt === "number" &&
    token.keycloakAccessTokenExpiresAt > now + 30_000
  );
}

export async function refreshKeycloakToken(
  token: KeycloakSessionToken,
  {
    clientId,
    clientSecret,
    fetcher = fetch,
    issuer,
    now = Date.now(),
  }: RefreshOptions,
): Promise<KeycloakSessionToken> {
  if (!token.keycloakRefreshToken) {
    return { ...token, keycloakRefreshError: "refresh_failed" };
  }

  try {
    const response = await fetcher(`${issuer}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: clientId,
        client_secret: clientSecret,
        grant_type: "refresh_token",
        refresh_token: token.keycloakRefreshToken,
      }),
    });
    const payload = (await response.json()) as RefreshResponse;
    if (!response.ok || !payload.access_token || !payload.expires_in) {
      throw new Error("Keycloak token refresh failed");
    }

    return {
      ...token,
      keycloakAccessToken: payload.access_token,
      keycloakAccessTokenExpiresAt: now + payload.expires_in * 1000,
      keycloakIdToken: payload.id_token ?? token.keycloakIdToken,
      keycloakRefreshError: undefined,
      keycloakRefreshToken: payload.refresh_token ?? token.keycloakRefreshToken,
    };
  } catch {
    return { ...token, keycloakRefreshError: "refresh_failed" };
  }
}
