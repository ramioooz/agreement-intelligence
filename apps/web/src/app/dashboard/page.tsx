import { redirect } from "next/navigation";

import { auth, signOut } from "@/auth";
import { DashboardShell } from "@/components/dashboard-shell";
import { buildKeycloakLogoutUrl } from "@/lib/keycloak-logout";

export default async function DashboardPage() {
  const session = await auth();

  if (!session?.user) {
    redirect("/sign-in");
  }

  async function signOutOfApplication() {
    "use server";

    await signOut({ redirectTo: buildKeycloakLogoutUrl() });
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
