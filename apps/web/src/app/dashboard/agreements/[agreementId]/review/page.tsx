import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import {
  ReviewWorkspace,
  type ReviewEvidence,
} from "@/components/review-workspace";
import {
  documentDownloadPath,
  getAgreement,
  getDocumentAnalysis,
  type AgreementScope,
} from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import { listPlaybookEvaluations } from "@/lib/review-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

async function loadReview(
  scope: AgreementScope,
  agreementId: string,
  token: string | undefined,
) {
  try {
    const evaluations = await listPlaybookEvaluations({
      scope,
      agreementId,
      token,
    });
    const latestEvaluation = evaluations[0];
    if (!latestEvaluation) return { analysis: undefined, latestEvaluation };
    if (!latestEvaluation.processing_job_id) return null;
    const analysis = await getDocumentAnalysis({
      scope,
      agreementId,
      processingJobId: latestEvaluation.processing_job_id,
      token,
    });
    if (analysis.schema_version !== latestEvaluation.analysis_version) {
      return null;
    }
    return { analysis, latestEvaluation };
  } catch {
    return null;
  }
}

async function ReviewWorkspaceContent({
  agreementId,
  scope,
}: {
  agreementId: string;
  scope: AgreementScope;
}) {
  const token = await getKeycloakAccessToken(await headers());
  let agreement;
  try {
    agreement = await getAgreement({ scope, agreementId, token });
  } catch {
    notFound();
  }

  const review = await loadReview(scope, agreementId, token);
  if (!review) {
    return (
      <ReviewWorkspace
        agreementId={agreement.id}
        agreementTitle={agreement.title}
        state="error"
      />
    );
  }
  const evidence: ReviewEvidence[] =
    review.analysis?.document.pages.flatMap((page) =>
      page.blocks.map((block) => ({
        citationId: block.anchor_id,
        kind: block.kind,
        pageNumber: page.number,
        text: block.text,
      })),
    ) ?? [];
  const file = agreement.files[0];
  return (
    <ReviewWorkspace
      agreementId={agreement.id}
      agreementTitle={agreement.title}
      documentUrl={
        file
          ? documentDownloadPath({ scope, objectKey: file.storage_key })
          : undefined
      }
      evidence={evidence}
      findings={review.latestEvaluation?.findings ?? []}
    />
  );
}

export default async function AgreementReviewPage({
  params,
}: {
  params: Promise<{ agreementId: string }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const scope = scopeFromEnvironment();
  if (!scope) notFound();
  const { agreementId } = await params;
  const workspace = await ReviewWorkspaceContent({ agreementId, scope });

  return <main className="mx-auto max-w-7xl px-6 py-10">{workspace}</main>;
}
