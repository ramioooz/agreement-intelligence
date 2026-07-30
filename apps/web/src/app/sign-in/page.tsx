import { signIn } from "@/auth";
import { SignInPanel } from "@/components/sign-in-panel";

export default function SignInPage() {
  async function signInWithKeycloak() {
    "use server";

    await signIn("keycloak", { redirectTo: "/dashboard" });
  }

  return <SignInPanel signInAction={signInWithKeycloak} />;
}
