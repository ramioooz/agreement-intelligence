import { redirect } from "next/navigation";
import { headers } from "next/headers";

import { auth, signOut } from "@/auth";
import { DashboardShell } from "@/components/dashboard-shell";
import { getKeycloakIdTokenHint } from "@/lib/auth-session-token";
import { buildKeycloakLogoutUrl } from "@/lib/keycloak-logout";

export default async function DashboardPage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/sign-in");
  }

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
    />
  );
}
