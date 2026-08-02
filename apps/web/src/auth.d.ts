import "next-auth";
import "@auth/core/jwt";

declare module "next-auth" {
  interface User {
    id?: string;
  }

  interface Session {
    user?: User;
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    keycloakIdToken?: string;
    keycloakAccessToken?: string;
    keycloakAccessTokenExpiresAt?: number;
    keycloakRefreshError?: "refresh_failed";
    keycloakRefreshToken?: string;
  }
}
