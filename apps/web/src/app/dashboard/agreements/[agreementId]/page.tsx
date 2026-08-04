import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { AgreementDetail } from "@/components/agreement-detail";
import {
  documentDownloadPath,
  getDocumentAnalysis,
  getAgreement,
  getWorkspaceCapabilities,
  listAgreementVersions,
  uploadAgreementVersion,
  type AgreementScope,
  type AgreementSummary,
  type AgreementVersionList,
  type DocumentAnalysis,
} from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import {
  listEligiblePlaybooks,
  recordPlaybookOverride,
  type PlaybookVersion,
} from "@/lib/playbook-api";
import {
  getProcessingJob,
  requeueProcessingJob,
  retryProcessingJob,
  submitProcessingJob,
  type ProcessingJob,
} from "@/lib/processing-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

async function loadDocumentAnalysis(
  scope: AgreementScope,
  agreementId: string,
): Promise<DocumentAnalysis | undefined> {
  try {
    return await getDocumentAnalysis({
      scope,
      agreementId,
      token: await getKeycloakAccessToken(await headers()),
    });
  } catch {
    return undefined;
  }
}

async function loadAgreement(
  scope: AgreementScope,
  agreementId: string,
): Promise<AgreementSummary | null> {
  try {
    return await getAgreement({
      scope,
      agreementId,
      token: await getKeycloakAccessToken(await headers()),
    });
  } catch {
    return null;
  }
}

async function loadProcessingJob(
  scope: AgreementScope,
  agreementId: string,
  jobId: string,
): Promise<ProcessingJob | undefined> {
  try {
    return await getProcessingJob({
      scope,
      agreementId,
      jobId,
      token: await getKeycloakAccessToken(await headers()),
    });
  } catch {
    return undefined;
  }
}

async function loadEligiblePlaybooks(
  scope: AgreementScope,
  agreementId: string,
): Promise<PlaybookVersion[] | undefined> {
  try {
    return await listEligiblePlaybooks({
      scope,
      agreementId,
      token: await getKeycloakAccessToken(await headers()),
    });
  } catch {
    return undefined;
  }
}

async function loadAgreementVersions(
  scope: AgreementScope,
  agreementId: string,
): Promise<AgreementVersionList | undefined> {
  try {
    return await listAgreementVersions({
      scope,
      agreementId,
      token: await getKeycloakAccessToken(await headers()),
    });
  } catch {
    return undefined;
  }
}

async function canUploadAgreementVersion(
  scope: AgreementScope,
): Promise<boolean> {
  try {
    return (
      await getWorkspaceCapabilities({
        scope,
        token: await getKeycloakAccessToken(await headers()),
      })
    ).agreements_update;
  } catch {
    return false;
  }
}

export default async function AgreementDetailPage({
  params,
}: {
  params: Promise<{ agreementId: string }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const scope = scopeFromEnvironment();
  if (!scope) notFound();
  const { agreementId } = await params;
  const agreement = await loadAgreement(scope, agreementId);
  if (!agreement) notFound();
  const file = agreement.files[0];
  const jobId = agreement.audit_metadata.processing_job_id;
  const processingJob = jobId
    ? await loadProcessingJob(scope, agreement.id, jobId)
    : undefined;
  const analysis = await loadDocumentAnalysis(scope, agreement.id);
  const eligiblePlaybooks = await loadEligiblePlaybooks(scope, agreement.id);
  const [versionHistory, canUploadVersion] = await Promise.all([
    loadAgreementVersions(scope, agreement.id),
    canUploadAgreementVersion(scope),
  ]);
  const retryScope = scope;
  const retryAgreementId = agreement.id;
  const expectedCurrentVersion = Math.max(
    0,
    ...(versionHistory?.items.map((version) => version.version_number) ?? []),
  );

  async function retryAction() {
    "use server";
    if (!jobId) return;
    await retryProcessingJob({
      scope: retryScope,
      agreementId: retryAgreementId,
      jobId,
      token: await getKeycloakAccessToken(await headers()),
    });
  }

  async function startAnalysisAction() {
    "use server";
    await submitProcessingJob({
      scope: retryScope,
      agreementId: retryAgreementId,
      idempotencyKey: crypto.randomUUID(),
      token: await getKeycloakAccessToken(await headers()),
    });
    revalidatePath(`/dashboard/agreements/${retryAgreementId}`);
  }

  async function requeueAction() {
    "use server";
    if (!jobId) return;
    await requeueProcessingJob({
      scope: retryScope,
      agreementId: retryAgreementId,
      jobId,
      token: await getKeycloakAccessToken(await headers()),
    });
    revalidatePath(`/dashboard/agreements/${retryAgreementId}`);
  }

  async function overridePlaybookAction(formData: FormData) {
    "use server";

    const playbookVersionId = String(formData.get("playbookVersionId") ?? "");
    const reason = String(formData.get("reason") ?? "").trim();
    if (!playbookVersionId || !reason) return;
    await recordPlaybookOverride({
      scope: retryScope,
      agreementId: retryAgreementId,
      playbookVersionId,
      reason,
      token: await getKeycloakAccessToken(await headers()),
    });
    revalidatePath(`/dashboard/agreements/${retryAgreementId}`);
  }

  async function uploadVersionAction(formData: FormData) {
    "use server";

    const file = formData.get("file");
    if (!(file instanceof File) || file.size === 0) return;
    await uploadAgreementVersion({
      scope: retryScope,
      agreementId: retryAgreementId,
      file,
      expectedCurrentVersion,
      idempotencyKey: crypto.randomUUID(),
      token: await getKeycloakAccessToken(await headers()),
    });
    revalidatePath(`/dashboard/agreements/${retryAgreementId}`);
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <AgreementDetail
        agreement={agreement}
        documentUrl={
          file
            ? documentDownloadPath({ scope, objectKey: file.storage_key })
            : undefined
        }
        processingJob={processingJob}
        analysis={analysis}
        retryAction={processingJob?.retry_permitted ? retryAction : undefined}
        requeueAction={
          processingJob?.state === "queued" ? requeueAction : undefined
        }
        startAnalysisAction={
          !processingJob && file ? startAnalysisAction : undefined
        }
        versions={versionHistory?.items}
        uploadVersionAction={canUploadVersion ? uploadVersionAction : undefined}
      />
      {eligiblePlaybooks && eligiblePlaybooks.length > 0 ? (
        <section className="mt-8 rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="text-xl font-semibold">Override review playbook</h2>
          <p className="mt-1 text-sm text-slate-600">
            Use only for an exceptional agreement. The selected published
            version and your reason are immutable audit evidence.
          </p>
          <form
            action={overridePlaybookAction}
            className="mt-4 grid gap-4 md:grid-cols-2"
          >
            <label className="grid gap-1.5 text-sm font-medium">
              Eligible playbook
              <select
                className="rounded-lg border border-slate-300 px-3 py-2"
                name="playbookVersionId"
                required
              >
                {eligiblePlaybooks.map((playbook) => (
                  <option key={playbook.id} value={playbook.id}>
                    {playbook.name} · Version {playbook.version} ·{" "}
                    {playbook.jurisdiction}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Override reason
              <input
                className="rounded-lg border border-slate-300 px-3 py-2"
                name="reason"
                required
              />
            </label>
            <button
              className="w-fit rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"
              type="submit"
            >
              Record override
            </button>
          </form>
        </section>
      ) : null}
    </main>
  );
}
