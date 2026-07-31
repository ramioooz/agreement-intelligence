import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";

import { isAllowedPostSignOutRedirect } from "@/lib/keycloak-logout";

const localIssuer =
  process.env.OIDC_ISSUER ??
  "http://localhost:8080/realms/agreement-intelligence";
const internalIssuer = process.env.OIDC_INTERNAL_ISSUER ?? localIssuer;

function endpoint(path: string, issuer = internalIssuer): string {
  return `${issuer}/protocol/openid-connect/${path}`;
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  secret: process.env.AUTH_SECRET,
  pages: {
    signIn: "/sign-in",
  },
  session: {
    maxAge: 8 * 60 * 60,
    strategy: "jwt",
  },
  cookies: {
    sessionToken: {
      name:
        process.env.NODE_ENV === "production"
          ? "__Secure-agreement-intelligence.session-token"
          : "agreement-intelligence.session-token",
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
  },
  providers: [
    Keycloak({
      clientId: process.env.OIDC_CLIENT_ID ?? "agreement-intelligence-web",
      clientSecret: process.env.OIDC_CLIENT_SECRET ?? "",
      issuer: localIssuer,
      authorization: {
        url: endpoint("auth", localIssuer),
        params: {
          scope: "openid profile email",
        },
      },
      token: endpoint("token"),
      userinfo: endpoint("userinfo"),
      checks: ["pkce", "state"],
    }),
  ],
  callbacks: {
    authorized({ auth: session }) {
      return Boolean(session?.user);
    },
    redirect({ url, baseUrl }) {
      if (url.startsWith("/")) {
        return `${baseUrl}${url}`;
      }

      if (new URL(url).origin === baseUrl) {
        return url;
      }

      if (isAllowedPostSignOutRedirect(url)) {
        return url;
      }

      return baseUrl;
    },
    jwt({ token, account, profile }) {
      if (profile?.sub) {
        token.sub = profile.sub;
      }

      if (account?.id_token) {
        token.keycloakIdToken = account.id_token;
      }

      if (account?.access_token) {
        token.keycloakAccessToken = account.access_token;
      }

      return token;
    },
    session({ session, token }) {
      if (session.user && token.sub) {
        session.user.id = token.sub;
      }

      return session;
    },
  },
});
