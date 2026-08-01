import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { AgreementDetail } from "@/components/agreement-detail";
import {
  documentDownloadPath,
  getDocumentAnalysis,
  getAgreement,
  type AgreementScope,
  type AgreementSummary,
  type DocumentAnalysis,
} from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
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
  const retryScope = scope;
  const retryAgreementId = agreement.id;

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
      />
    </main>
  );
}
