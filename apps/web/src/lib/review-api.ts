import "server-only";

import { ApiRequestError, type AgreementScope } from "@/lib/agreement-api";

export type FindingResult =
  "satisfied" | "missing" | "non_compliant" | "needs_review";

export type RiskPayload = {
  version: "playbook-risk.v1";
  severity: string;
  risk_rationale: string;
  risk_confidence: number;
  review_status: string;
  citation_ids: string[];
  model_explanation: string | null;
};

export type FallbackSuggestion = {
  version: "playbook-fallback-suggestion.v1";
  rule_id: string;
  playbook_version_id: string;
  suggested_language: string | null;
  review_recommendation: string;
  citation_ids: string[];
  comparison_kind: "clause_differs_from_approved_position" | null;
  comparison: string | null;
  ai_generated: boolean;
};

export type PlaybookFindingResponse = {
  id: string;
  rule_id: string;
  rule_title: string;
  clause_type: string;
  reviewer_guidance: string;
  result: FindingResult;
  severity: string;
  confidence: number;
  method: "deterministic" | "semantic";
  citation_ids: string[];
  playbook_version_id: string;
  extraction_version: string;
  review_state: string;
  risk: RiskPayload;
  fallback_suggestions: FallbackSuggestion[];
};

export type PlaybookEvaluationResponse = {
  id: string;
  agreement_id: string;
  processing_job_id: string | null;
  playbook_version_id: string;
  analysis_version: string;
  extraction_version: string;
  state: string;
  findings: PlaybookFindingResponse[];
  created_at: string;
};

type ListPlaybookEvaluationsOptions = {
  baseUrl?: string;
  scope: AgreementScope;
  agreementId: string;
  token?: string;
  fetcher?: typeof fetch;
};

const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function listPlaybookEvaluations({
  baseUrl = defaultBaseUrl,
  scope,
  agreementId,
  token,
  fetcher = fetch,
}: ListPlaybookEvaluationsOptions): Promise<PlaybookEvaluationResponse[]> {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
  const response = await fetcher(
    `${baseUrl.replace(/\/$/, "")}/agreements/${agreementId}/playbook-evaluations?${params}`,
    {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!response.ok) {
    throw new ApiRequestError(
      "The review findings could not be loaded.",
      response.status,
    );
  }
  return response.json() as Promise<PlaybookEvaluationResponse[]>;
}
