import { getToken } from "next-auth/jwt";

export const sessionCookieName =
  process.env.NODE_ENV === "production"
    ? "__Secure-agreement-intelligence.session-token"
    : "agreement-intelligence.session-token";

export async function getKeycloakIdTokenHint(
  requestHeaders: Headers,
): Promise<string | undefined> {
  if (!process.env.AUTH_SECRET) {
    return undefined;
  }

  const token = await getToken({
    cookieName: sessionCookieName,
    req: {
      headers: requestHeaders,
    },
    secret: process.env.AUTH_SECRET,
  });

  return typeof token?.keycloakIdToken === "string"
    ? token.keycloakIdToken
    : undefined;
}

export async function getKeycloakAccessToken(
  requestHeaders: Headers,
): Promise<string | undefined> {
  if (!process.env.AUTH_SECRET) {
    return undefined;
  }

  const token = await getToken({
    cookieName: sessionCookieName,
    req: { headers: requestHeaders },
    secret: process.env.AUTH_SECRET,
  });

  return typeof token?.keycloakAccessToken === "string"
    ? token.keycloakAccessToken
    : undefined;
}
