import { headers } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { PlaybookVersionList } from "@/components/playbook-version-list";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  createPlaybook,
  listPlaybooks,
  type PlaybookVersion,
} from "@/lib/playbook-api";
import {
  getWorkspaceCapabilities,
  type AgreementScope,
} from "@/lib/agreement-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

async function requirePlaybookAccessToken(): Promise<string> {
  const token = await getKeycloakAccessToken(await headers());
  if (!token) {
    redirect("/sign-in?callbackUrl=%2Fdashboard%2Fplaybooks");
  }
  return token;
}

async function loadPlaybooks(
  scope: AgreementScope,
  token: string | null | undefined,
): Promise<PlaybookVersion[] | null> {
  try {
    return await listPlaybooks({ scope, token: token ?? undefined });
  } catch {
    return null;
  }
}

async function canManagePlaybooks(
  scope: AgreementScope,
  token: string | null | undefined,
): Promise<boolean> {
  try {
    return (
      await getWorkspaceCapabilities({ scope, token: token ?? undefined })
    ).playbooks_manage;
  } catch {
    return false;
  }
}

export default async function PlaybooksPage() {
  if (!(await auth())?.user) redirect("/sign-in");
  const scope = scopeFromEnvironment();
  if (!scope)
    return (
      <main className="mx-auto max-w-7xl px-6 py-10">
        <p role="alert">A playbook workspace is not configured.</p>
      </main>
    );
  const configuredScope = scope;
  const token = await requirePlaybookAccessToken();
  const [playbooks, canManage] = await Promise.all([
    loadPlaybooks(configuredScope, token),
    canManagePlaybooks(configuredScope, token),
  ]);
  if (!playbooks)
    return (
      <main className="mx-auto max-w-7xl px-6 py-10">
        <p role="alert">
          Unable to load legal playbooks. Check your access and try again.
        </p>
      </main>
    );

  async function createDraft(formData: FormData) {
    "use server";

    const name = String(formData.get("name") ?? "").trim();
    const agreementFamily = String(
      formData.get("agreementFamily") ?? "",
    ).trim();
    if (!name || !agreementFamily) return;
    const created = await createPlaybook({
      scope: configuredScope,
      name,
      agreementFamily,
      documentDirection: String(formData.get("documentDirection") ?? "any") as
        "any" | "first_party" | "counterparty",
      jurisdiction:
        String(formData.get("jurisdiction") ?? "any").trim() || "any",
      priority: Number(formData.get("priority") ?? 100),
      token: await requirePlaybookAccessToken(),
    });
    redirect(
      `/dashboard/playbooks/${created.playbook_id}?version=${created.version}`,
    );
  }

  return (
    <main className="mx-auto max-w-7xl space-y-8 px-6 py-10">
      <Link
        className="inline-flex text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-950 hover:underline"
        href="/dashboard"
      >
        Back to dashboard
      </Link>
      <PlaybookVersionList playbooks={playbooks} />
      {canManage ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="text-xl font-semibold">Create playbook draft</h2>
          <form action={createDraft} className="mt-4 grid gap-4 md:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium">
              Playbook name
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                name="name"
                required
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Agreement family
              <select
                className="rounded-lg border border-slate-300 px-3 py-2"
                defaultValue="client_agreement"
                name="agreementFamily"
              >
                <option value="client_agreement">Client Agreement</option>
                <option value="liquidity_provider_agreement">
                  Liquidity Provider Agreement
                </option>
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Document direction
              <select
                className="rounded-lg border border-slate-300 px-3 py-2"
                defaultValue="any"
                name="documentDirection"
              >
                <option value="any">Any direction</option>
                <option value="first_party">Our paper</option>
                <option value="counterparty">Counterparty paper</option>
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Jurisdiction
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                defaultValue="any"
                name="jurisdiction"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Routing priority
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                defaultValue="100"
                max="1000"
                min="0"
                name="priority"
                type="number"
              />
            </label>
            <p className="text-sm text-slate-600 md:col-span-2">
              Choose the recognized agreement family governed by this playbook.
            </p>
            <button
              className="w-fit rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
              type="submit"
            >
              Create draft
            </button>
          </form>
        </section>
      ) : (
        <p className="rounded-xl border border-slate-200 bg-white p-5 text-slate-600">
          You have read-only access to legal playbooks.
        </p>
      )}
    </main>
  );
}
