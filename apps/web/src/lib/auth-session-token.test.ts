import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/jwt", () => ({
  getToken: vi.fn(),
}));
vi.mock("@/auth", () => ({
  handlers: { GET: vi.fn() },
}));

import { handlers } from "@/auth";
import {
  getKeycloakAccessTokenResult,
  sessionCookieName,
} from "@/lib/auth-session-token";
import { getToken } from "next-auth/jwt";

const mockedGetToken = vi.mocked(getToken);
const mockedSessionHandler = vi.mocked(handlers.GET);

describe("getKeycloakAccessTokenResult", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it("persists a rotated refresh token for the next protected request", async () => {
    vi.stubEnv("AUTH_SECRET", "test-auth-secret");
    mockedGetToken.mockImplementation(async ({ req }) =>
      new Headers(req.headers).get("cookie")?.includes("rotated-session-cookie")
        ? {
            keycloakAccessToken: "renewed-access-token",
            keycloakAccessTokenExpiresAt: Date.now() + 300_000,
            keycloakRefreshToken: "rotated-refresh-token",
          }
        : {
            keycloakAccessToken: "expired-access-token",
            keycloakAccessTokenExpiresAt: 1,
            keycloakRefreshToken: "original-refresh-token",
          },
    );
    mockedSessionHandler.mockResolvedValue(
      new Response(null, {
        headers: {
          "Set-Cookie": `${sessionCookieName}=rotated-session-cookie; Path=/; HttpOnly; SameSite=Lax`,
        },
      }),
    );

    const refreshed = await getKeycloakAccessTokenResult(
      new Headers({ Cookie: `${sessionCookieName}=expired-session-cookie` }),
    );
    const nextRequest = await getKeycloakAccessTokenResult(
      new Headers({
        Cookie: refreshed.refreshedSessionCookies?.join("; ") ?? "",
      }),
    );

    expect(refreshed).toMatchObject({
      accessToken: "renewed-access-token",
      refreshedSessionCookies: expect.any(Array),
    });
    expect(nextRequest).toEqual({ accessToken: "renewed-access-token" });
    expect(mockedSessionHandler).toHaveBeenCalledTimes(1);
  });

  it("preserves all Auth.js session-cookie chunks after refresh", async () => {
    vi.stubEnv("AUTH_SECRET", "test-auth-secret");
    mockedGetToken.mockImplementation(async ({ req }) =>
      new Headers(req.headers).get("cookie")?.includes("renewed-second")
        ? {
            keycloakAccessToken: "renewed-access-token",
            keycloakAccessTokenExpiresAt: Date.now() + 300_000,
            keycloakRefreshToken: "rotated-refresh-token",
          }
        : {
            keycloakAccessToken: "expired-access-token",
            keycloakAccessTokenExpiresAt: 1,
            keycloakRefreshToken: "original-refresh-token",
          },
    );
    mockedSessionHandler.mockResolvedValue({
      headers: {
        getSetCookie: () => [
          `${sessionCookieName}.0=renewed-first; Path=/; HttpOnly`,
          `${sessionCookieName}.1=renewed-second; Path=/; HttpOnly`,
        ],
      },
    } as unknown as Response);

    const refreshed = await getKeycloakAccessTokenResult(
      new Headers({
        Cookie: `${sessionCookieName}.0=stale-first; ${sessionCookieName}.1=stale-second`,
      }),
    );

    expect(refreshed.refreshedSessionCookies).toHaveLength(2);
    expect(refreshed.accessToken).toBe("renewed-access-token");
  });
});
