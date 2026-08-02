import { handlers } from "@/auth";
import { getToken } from "next-auth/jwt";
import { NextRequest } from "next/server";

import {
  hasUsableKeycloakAccessToken,
  type KeycloakSessionToken,
} from "@/lib/keycloak-token";

export const sessionCookieName =
  process.env.NODE_ENV === "production"
    ? "__Secure-agreement-intelligence.session-token"
    : "agreement-intelligence.session-token";

export type KeycloakAccessTokenResult = {
  accessToken?: string;
  refreshedSessionCookies?: string[];
};

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
  return (await getKeycloakAccessTokenResult(requestHeaders)).accessToken;
}

export async function getKeycloakAccessTokenResult(
  requestHeaders: Headers,
): Promise<KeycloakAccessTokenResult> {
  if (!process.env.AUTH_SECRET) {
    return {};
  }

  const token = await getToken({
    cookieName: sessionCookieName,
    req: { headers: requestHeaders },
    secret: process.env.AUTH_SECRET,
  });

  const keycloakToken = token as KeycloakSessionToken | null;
  if (!keycloakToken) return {};
  if (hasUsableKeycloakAccessToken(keycloakToken)) {
    return { accessToken: keycloakToken.keycloakAccessToken };
  }

  const sessionResponse = await handlers.GET(
    new NextRequest(`${webOrigin()}/api/auth/session`, {
      headers: requestHeaders,
    }),
  );
  const refreshedSessionCookies = setCookieHeaders(sessionResponse.headers);
  if (!refreshedSessionCookies.length) return {};
  const refreshedToken = await getToken({
    cookieName: sessionCookieName,
    req: {
      headers: headersWithRefreshedSession(
        requestHeaders,
        refreshedSessionCookies,
      ),
    },
    secret: process.env.AUTH_SECRET,
  });
  const refreshed = refreshedToken as KeycloakSessionToken | null;
  if (refreshed?.keycloakRefreshError || !refreshed?.keycloakAccessToken)
    return {};

  return {
    accessToken: refreshed.keycloakAccessToken,
    refreshedSessionCookies,
  };
}

export function applyRefreshedKeycloakSession(
  response: Response,
  session: KeycloakAccessTokenResult,
): Response {
  if (!session.refreshedSessionCookies) return response;

  for (const cookie of session.refreshedSessionCookies)
    response.headers.append("Set-Cookie", cookie);
  return response;
}

function webOrigin(): string {
  return process.env.WEB_PUBLIC_ORIGIN ?? "http://localhost:3000";
}

function setCookieHeaders(headers: Headers): string[] {
  const headersWithSetCookie = headers as Headers & {
    getSetCookie?: () => string[];
  };
  const cookies = headersWithSetCookie.getSetCookie?.();
  if (cookies?.length) return cookies;
  const joined = headers.get("set-cookie");
  return joined ? joined.split(/,(?=\s*[^;=]+=[^;]+)/) : [];
}

function headersWithRefreshedSession(
  requestHeaders: Headers,
  sessionCookies: string[],
): Headers {
  const cookies = Object.fromEntries(
    (requestHeaders.get("cookie") ?? "")
      .split(";")
      .map((entry) => entry.trim().split("=", 2))
      .filter(([name, value]) => Boolean(name && value))
      .filter(([name]) => !name.startsWith(sessionCookieName)),
  );
  for (const cookie of sessionCookies) {
    const [name, value] = cookie.split(";", 1)[0].split("=", 2);
    if (name && value) cookies[name] = value;
  }

  const headers = new Headers(requestHeaders);
  headers.set(
    "cookie",
    Object.entries(cookies)
      .map(([name, value]) => `${name}=${value}`)
      .join("; "),
  );
  return headers;
}
