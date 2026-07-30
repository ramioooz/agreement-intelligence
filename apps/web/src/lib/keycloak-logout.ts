type KeycloakLogoutConfig = {
  oidcClientId?: string;
  oidcIssuer?: string;
  webPublicOrigin?: string;
};

const defaultOidcClientId = "agreement-intelligence-web";
const defaultOidcIssuer = "http://localhost:8080/realms/agreement-intelligence";
const defaultWebPublicOrigin = "http://localhost:3000";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function logoutEndpoint(issuer: string): URL {
  return new URL(`${trimTrailingSlash(issuer)}/protocol/openid-connect/logout`);
}

function signInUrl(webPublicOrigin: string): string {
  return `${trimTrailingSlash(webPublicOrigin)}/sign-in`;
}

export function buildKeycloakLogoutUrl({
  oidcClientId = process.env.OIDC_CLIENT_ID ?? defaultOidcClientId,
  oidcIssuer = process.env.OIDC_ISSUER ?? defaultOidcIssuer,
  webPublicOrigin = process.env.WEB_PUBLIC_ORIGIN ??
    process.env.AUTH_URL ??
    defaultWebPublicOrigin,
}: KeycloakLogoutConfig = {}): string {
  const logoutUrl = logoutEndpoint(oidcIssuer);

  logoutUrl.searchParams.set("client_id", oidcClientId);
  logoutUrl.searchParams.set(
    "post_logout_redirect_uri",
    signInUrl(webPublicOrigin),
  );

  return logoutUrl.toString();
}

export function isAllowedPostSignOutRedirect(
  redirectUrl: string,
  {
    oidcClientId = process.env.OIDC_CLIENT_ID ?? defaultOidcClientId,
    oidcIssuer = process.env.OIDC_ISSUER ?? defaultOidcIssuer,
    webPublicOrigin = process.env.WEB_PUBLIC_ORIGIN ??
      process.env.AUTH_URL ??
      defaultWebPublicOrigin,
  }: KeycloakLogoutConfig = {},
): boolean {
  let parsedRedirectUrl: URL;

  try {
    parsedRedirectUrl = new URL(redirectUrl);
  } catch {
    return false;
  }

  const expectedLogoutEndpoint = logoutEndpoint(oidcIssuer);

  return (
    parsedRedirectUrl.origin === expectedLogoutEndpoint.origin &&
    parsedRedirectUrl.pathname === expectedLogoutEndpoint.pathname &&
    parsedRedirectUrl.searchParams.get("client_id") === oidcClientId &&
    parsedRedirectUrl.searchParams.get("post_logout_redirect_uri") ===
      signInUrl(webPublicOrigin)
  );
}
