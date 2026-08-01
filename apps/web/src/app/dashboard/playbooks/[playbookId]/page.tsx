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
  createPlaybookVersion,
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
        <form action={createNextDraft}>
          <button
            className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
            type="submit"
          >
            Create next draft
          </button>
        </form>
      ) : null}
    </main>
  );
}
