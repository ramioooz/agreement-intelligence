import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AgreementRepository } from "@/components/agreement-repository";
import { AgreementUploadForm } from "@/components/agreement-upload-form";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  listAgreements,
  getWorkspaceCapabilities,
  type AgreementPage,
  type AgreementStatus,
  type AgreementScope,
} from "@/lib/agreement-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

async function loadAgreements(
  scope: AgreementScope,
  options: {
    query?: string;
    status?: AgreementStatus;
    agreementType?: string;
    cursor?: string;
  },
): Promise<AgreementPage | null> {
  try {
    return await listAgreements({
      scope,
      token: await getKeycloakAccessToken(await headers()),
      ...options,
    });
  } catch {
    return null;
  }
}

async function canDeleteAgreements(
  scope: AgreementScope,
  token: string | null | undefined,
): Promise<boolean> {
  try {
    return (
      await getWorkspaceCapabilities({ scope, token: token ?? undefined })
    ).agreements_delete;
  } catch {
    return false;
  }
}

export default async function AgreementsPage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string;
    status?: string;
    type?: string;
    cursor?: string;
  }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const accessToken = await getKeycloakAccessToken(await headers());
  const params = await searchParams;
  const scope = scopeFromEnvironment();
  if (!scope)
    return (
      <main className="mx-auto max-w-7xl px-6 py-10">
        <AgreementRepository state="error" />
      </main>
    );
  const page = await loadAgreements(scope, {
    query: params.q,
    status: params.status as AgreementStatus | undefined,
    agreementType: params.type,
    cursor: params.cursor,
  });
  if (!page)
    return (
      <main className="mx-auto max-w-7xl px-6 py-10">
        <AgreementRepository state="error" />
      </main>
    );
  return (
    <main className="mx-auto max-w-7xl space-y-8 px-6 py-10">
      <AgreementRepository
        agreements={page.items}
        filters={{
          query: params.q ?? "",
          status: (params.status as AgreementStatus) ?? "all",
          agreementType: params.type ?? "all",
        }}
        nextCursor={page.page.next_cursor}
        canDelete={await canDeleteAgreements(scope, accessToken)}
      />
      <AgreementUploadForm />
    </main>
  );
}
