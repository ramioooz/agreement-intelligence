import { describe, expect, it } from "vitest";

import {
  buildKeycloakLogoutUrl,
  isAllowedPostSignOutRedirect,
} from "@/lib/keycloak-logout";

describe("buildKeycloakLogoutUrl", () => {
  it("builds an RP-initiated logout URL for the configured local realm", () => {
    const logoutUrl = new URL(
      buildKeycloakLogoutUrl({
        oidcClientId: "agreement-intelligence-web",
        oidcIssuer: "http://localhost:8080/realms/agreement-intelligence",
        webPublicOrigin: "http://localhost:3000",
      }),
    );

    expect(logoutUrl.origin).toBe("http://localhost:8080");
    expect(logoutUrl.pathname).toBe(
      "/realms/agreement-intelligence/protocol/openid-connect/logout",
    );
    expect(logoutUrl.searchParams.get("client_id")).toBe(
      "agreement-intelligence-web",
    );
    expect(logoutUrl.searchParams.get("post_logout_redirect_uri")).toBe(
      "http://localhost:3000/sign-in",
    );
  });
});

describe("isAllowedPostSignOutRedirect", () => {
  it("allows the configured Keycloak logout endpoint", () => {
    const logoutUrl = buildKeycloakLogoutUrl({
      oidcClientId: "agreement-intelligence-web",
      oidcIssuer: "http://localhost:8080/realms/agreement-intelligence",
      webPublicOrigin: "http://localhost:3000",
    });

    expect(
      isAllowedPostSignOutRedirect(logoutUrl, {
        oidcIssuer: "http://localhost:8080/realms/agreement-intelligence",
        webPublicOrigin: "http://localhost:3000",
      }),
    ).toBe(true);
  });

  it("rejects unrelated external redirects", () => {
    expect(
      isAllowedPostSignOutRedirect("https://example.test/logout", {
        oidcIssuer: "http://localhost:8080/realms/agreement-intelligence",
        oidcClientId: "agreement-intelligence-web",
        webPublicOrigin: "http://localhost:3000",
      }),
    ).toBe(false);
  });

  it("rejects Keycloak logout redirects for a different client", () => {
    const logoutUrl = new URL(
      buildKeycloakLogoutUrl({
        oidcClientId: "another-client",
        oidcIssuer: "http://localhost:8080/realms/agreement-intelligence",
        webPublicOrigin: "http://localhost:3000",
      }),
    );

    expect(
      isAllowedPostSignOutRedirect(logoutUrl.toString(), {
        oidcIssuer: "http://localhost:8080/realms/agreement-intelligence",
        oidcClientId: "agreement-intelligence-web",
        webPublicOrigin: "http://localhost:3000",
      }),
    ).toBe(false);
  });
});
