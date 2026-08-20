import { redirect } from "next/navigation";
import { headers } from "next/headers";

import { auth, signOut } from "@/auth";
import { DashboardShell } from "@/components/dashboard-shell";
import {
  getKeycloakAccessToken,
  getKeycloakIdTokenHint,
} from "@/lib/auth-session-token";
import { buildKeycloakLogoutUrl } from "@/lib/keycloak-logout";
import { getWorkspaceCapabilities } from "@/lib/agreement-api";

export default async function DashboardPage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/sign-in");
  }
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  const capabilities =
    organizationId && workspaceId
      ? await getWorkspaceCapabilities({
          scope: { organizationId, workspaceId },
          token: await getKeycloakAccessToken(await headers()),
        }).catch(() => undefined)
      : undefined;

  async function signOutOfApplication() {
    "use server";

    const idTokenHint = await getKeycloakIdTokenHint(await headers());

    await signOut({ redirectTo: buildKeycloakLogoutUrl({ idTokenHint }) });
  }

  return (
    <DashboardShell
      signOutAction={signOutOfApplication}
      user={{
        email: session.user.email,
        name: session.user.name,
      }}
      canManagePolicies={capabilities?.approval_policies_manage ?? false}
    />
  );
}
