import type { AgreementScope } from "@/lib/agreement-api";
import { ApiRequestError } from "@/lib/agreement-api";

export type ComparisonState = "queued" | "processing" | "completed" | "failed";
export type WordDiff = {
  operation: "equal" | "insert" | "delete";
  text: string;
};
export type VersionComparisonChange = {
  id: string;
  ordinal: number;
  alignment_kind:
    "matched" | "moved" | "split" | "merged" | "added" | "removed";
  baseline_element_ids: string[];
  target_element_ids: string[];
  baseline_citation_ids: string[];
  target_citation_ids: string[];
  word_diff: WordDiff[];
  confidence: number;
  review_required: boolean;
  severity: "none" | "low" | "medium" | "high" | "critical";
  legal_concepts: string[];
  rationale: string;
  provider_provenance: Record<string, unknown>;
};
export type VersionComparison = {
  id: string;
  agreement_id: string;
  baseline_version_id: string;
  target_version_id: string;
  processing_job_id: string | null;
  analysis_version: string;
  state: ComparisonState;
  failure_category: string | null;
  failure_message: string | null;
  analysis_provenance: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  changes: VersionComparisonChange[];
};

export async function createVersionComparison({
  baseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000",
  scope,
  agreementId,
  baselineVersionId,
  targetVersionId,
  token,
  idempotencyKey,
  fetcher = fetch,
}: {
  baseUrl?: string;
  scope: AgreementScope;
  agreementId: string;
  baselineVersionId?: string;
  targetVersionId?: string;
  token?: string;
  idempotencyKey: string;
  fetcher?: typeof fetch;
}): Promise<VersionComparison> {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
  const response = await fetcher(
    `${baseUrl.replace(/\/$/, "")}/agreements/${agreementId}/version-comparisons?${params}`,
    {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({
        ...(baselineVersionId
          ? { baseline_version_id: baselineVersionId }
          : {}),
        ...(targetVersionId ? { target_version_id: targetVersionId } : {}),
      }),
    },
  );
  if (!response.ok)
    throw new ApiRequestError(
      "Comparison could not be started.",
      response.status,
    );
  return response.json() as Promise<VersionComparison>;
}

export async function getVersionComparison({
  baseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000",
  scope,
  agreementId,
  comparisonId,
  token,
  fetcher = fetch,
}: {
  baseUrl?: string;
  scope: AgreementScope;
  agreementId: string;
  comparisonId: string;
  token?: string;
  fetcher?: typeof fetch;
}): Promise<VersionComparison> {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
  const response = await fetcher(
    `${baseUrl.replace(/\/$/, "")}/agreements/${agreementId}/version-comparisons/${comparisonId}?${params}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!response.ok)
    throw new ApiRequestError(
      "Comparison could not be loaded.",
      response.status,
    );
  return response.json() as Promise<VersionComparison>;
}
