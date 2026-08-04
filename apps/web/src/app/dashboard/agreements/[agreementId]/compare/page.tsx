import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { VersionComparisonWorkspace } from "@/components/version-comparison-workspace";
import {
  getDocumentAnalysis,
  getAgreement,
  listAgreementVersions,
  type AgreementScope,
  type AgreementVersionList,
  type DocumentAnalysis,
} from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  createVersionComparison,
  getVersionComparison,
  type VersionComparison,
} from "@/lib/version-comparison-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

async function safe<T>(load: () => Promise<T>): Promise<T | undefined> {
  try {
    return await load();
  } catch {
    return undefined;
  }
}

export default async function CompareAgreementPage({
  params,
  searchParams,
}: {
  params: Promise<{ agreementId: string }>;
  searchParams: Promise<{ comparison_id?: string }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const scope = scopeFromEnvironment();
  if (!scope) notFound();
  const resolvedScope = scope as AgreementScope;
  const { agreementId } = await params;
  const { comparison_id: comparisonId } = await searchParams;
  const token = await getKeycloakAccessToken(await headers());
  const agreement = await safe(() =>
    getAgreement({ scope: resolvedScope, agreementId, token }),
  );
  if (!agreement) notFound();
  const versions = await safe(() =>
    listAgreementVersions({ scope: resolvedScope, agreementId, token }),
  );
  const versionList: AgreementVersionList = versions ?? {
    items: [],
    current_version_id: null,
    comparison_baseline_version_id: null,
  };
  const completed = versionList.items
    .filter((version) => version.processing_state === "completed")
    .sort((left, right) => left.version_number - right.version_number);
  const baselineVersion = completed.at(-2);
  const targetVersion = completed.at(-1);
  const [baselineAnalysis, targetAnalysis, comparison] = await Promise.all([
    baselineVersion?.processing_job_id
      ? safe(() =>
          getDocumentAnalysis({
            scope: resolvedScope,
            agreementId,
            processingJobId: baselineVersion.processing_job_id ?? undefined,
            token,
          }),
        )
      : Promise.resolve(undefined),
    targetVersion?.processing_job_id
      ? safe(() =>
          getDocumentAnalysis({
            scope: resolvedScope,
            agreementId,
            processingJobId: targetVersion.processing_job_id ?? undefined,
            token,
          }),
        )
      : Promise.resolve(undefined),
    comparisonId
      ? safe(() =>
          getVersionComparison({
            scope: resolvedScope,
            agreementId,
            comparisonId,
            token,
          }),
        )
      : Promise.resolve(undefined),
  ]);

  async function compareAction(formData: FormData) {
    "use server";
    const baselineVersionId = String(formData.get("baseline_version_id") ?? "");
    const targetVersionId = String(formData.get("target_version_id") ?? "");
    if (
      !baselineVersionId ||
      !targetVersionId ||
      baselineVersionId === targetVersionId
    )
      return;
    const created = await createVersionComparison({
      scope: resolvedScope,
      agreementId,
      baselineVersionId,
      targetVersionId,
      idempotencyKey: crypto.randomUUID(),
      token: await getKeycloakAccessToken(await headers()),
    });
    redirect(
      `/dashboard/agreements/${agreementId}/compare?comparison_id=${created.id}`,
    );
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <a
        className="text-sm font-semibold underline-offset-4 hover:underline"
        href={`/dashboard/agreements/${agreementId}`}
      >
        Back to agreement
      </a>
      <VersionComparisonWorkspace
        versions={versionList.items}
        comparison={comparison as VersionComparison | undefined}
        baselineAnalysis={baselineAnalysis as DocumentAnalysis | undefined}
        targetAnalysis={targetAnalysis as DocumentAnalysis | undefined}
        compareAction={compareAction}
      />
    </main>
  );
}
