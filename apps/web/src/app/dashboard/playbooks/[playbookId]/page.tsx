import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { PlaybookEditor } from "@/components/playbook-editor";
import { PlaybookVersionList } from "@/components/playbook-version-list";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  addPlaybookRule,
  archivePlaybook,
  createPlaybookVersion,
  deletePlaybook,
  deletePlaybookRule,
  listPlaybooks,
  publishPlaybookVersion,
  updatePlaybookRule,
  type PlaybookRuleWrite,
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

export default async function PlaybookDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ playbookId: string }>;
  searchParams: Promise<{ version?: string }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const scope = scopeFromEnvironment();
  if (!scope) return notFound();
  const configuredScope = scope;
  const [{ playbookId }, query] = await Promise.all([params, searchParams]);
  const token = await getKeycloakAccessToken(await headers());
  const [playbooks, canManage] = await Promise.all([
    loadPlaybooks(configuredScope, token),
    canManagePlaybooks(configuredScope, token),
  ]);
  if (!playbooks) {
    return (
      <main className="mx-auto max-w-7xl px-6 py-10">
        <p role="alert">
          Unable to load this legal playbook. Check your access and try again.
        </p>
      </main>
    );
  }
  const versions = playbooks.filter(
    (version) => version.playbook_id === playbookId,
  );
  const selectedVersion = Number(query.version);
  const playbook =
    versions.find((version) => version.version === selectedVersion) ??
    [...versions].sort((left, right) => right.version - left.version)[0];
  if (!playbook) notFound();
  const detailPath = `/dashboard/playbooks/${playbookId}`;

  async function addRule(rule: PlaybookRuleWrite) {
    "use server";

    await addPlaybookRule({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      version: playbook.version,
      rule,
    });
    revalidatePath(detailPath);
  }

  async function updateRule(ruleId: string, rule: PlaybookRuleWrite) {
    "use server";

    await updatePlaybookRule({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      version: playbook.version,
      ruleId,
      rule,
    });
    revalidatePath(detailPath);
  }

  async function deleteRule(ruleId: string) {
    "use server";

    await deletePlaybookRule({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      version: playbook.version,
      ruleId,
    });
    revalidatePath(detailPath);
  }

  async function publish() {
    "use server";

    await publishPlaybookVersion({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      version: playbook.version,
    });
    revalidatePath(detailPath);
  }

  async function createNextDraft() {
    "use server";

    const created = await createPlaybookVersion({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      sourceVersion: playbook.version,
    });
    redirect(`${detailPath}?version=${created.version}`);
  }

  async function archive(formData: FormData) {
    "use server";

    const reason = String(formData.get("reason") ?? "").trim();
    if (!reason) return;
    await archivePlaybook({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      reason,
    });
    redirect("/dashboard/playbooks");
  }

  async function removeDraft(formData: FormData) {
    "use server";

    const reason = String(formData.get("reason") ?? "").trim();
    if (!reason) return;
    await deletePlaybook({
      scope: configuredScope,
      token: await getKeycloakAccessToken(await headers()),
      playbookId,
      reason,
    });
    redirect("/dashboard/playbooks");
  }

  return (
    <main className="mx-auto max-w-7xl space-y-8 px-6 py-10">
      <Link
        className="inline-flex text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-950 hover:underline"
        href="/dashboard/playbooks"
      >
        Back to playbooks
      </Link>
      <PlaybookVersionList
        currentPlaybookId={playbookId}
        playbooks={versions}
      />
      <PlaybookEditor
        addRuleAction={addRule}
        canManage={canManage}
        deleteRuleAction={deleteRule}
        playbook={playbook}
        publishAction={publish}
        updateRuleAction={updateRule}
      />
      {canManage && playbook.status === "published" ? (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
          <form action={createNextDraft}>
            <button
              className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
              type="submit"
            >
              Create next draft
            </button>
          </form>
          <form action={archive} className="grid gap-3 md:grid-cols-[1fr_auto]">
            <label className="grid gap-1.5 text-sm font-medium">
              Archive reason
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                name="reason"
                required
              />
            </label>
            <button
              className="self-end rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"
              type="submit"
            >
              Archive playbook
            </button>
          </form>
          <p className="text-sm text-slate-600">
            Archiving stops future routing but retains this version for prior
            reviews and reports.
          </p>
        </section>
      ) : canManage &&
        playbook.status === "draft" &&
        !versions.some((version) => version.status === "published") ? (
        <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5">
          <h2 className="text-xl font-semibold">Delete draft playbook</h2>
          <p className="mt-1 text-sm text-slate-700">
            Draft playbooks are permanently removed. Published policies must be
            archived instead.
          </p>
          <form
            action={removeDraft}
            className="mt-4 grid gap-3 md:grid-cols-[1fr_auto]"
          >
            <label className="grid gap-1.5 text-sm font-medium">
              Deletion reason
              <input
                className="rounded-lg border border-rose-300 bg-white px-3 py-2"
                name="reason"
                required
              />
            </label>
            <button
              className="self-end rounded-full bg-rose-700 px-4 py-2 text-sm font-semibold text-white"
              type="submit"
            >
              Delete draft
            </button>
          </form>
        </section>
      ) : null}
    </main>
  );
}
