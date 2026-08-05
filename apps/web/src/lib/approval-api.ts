import type { AgreementScope } from "@/lib/agreement-api";

export type ReviewAssignment = {
  id: string;
  review_id: string;
  assignee_id: string;
  assigned_by: string;
  predecessor_assignment_id: string | null;
  due_at: string | null;
  status: string;
  created_at: string;
};

export type ReviewCase = {
  id: string;
  agreement_id: string;
  agreement_version_id: string | null;
  state: string;
  created_by: string;
  revision: number;
  created_at: string;
};

export type ReviewComment = {
  id: string;
  review_id: string;
  finding_id: string | null;
  agreement_version_id: string | null;
  author_id: string;
  body: string;
  created_at: string;
};

export type ReviewNotificationSummary = { unread_count: number };

export type ApprovalPolicyStage = {
  id?: string;
  ordinal?: number;
  name: string;
  approval_mode: "any" | "all" | "quorum";
  quorum_count: number | null;
  eligible_role_keys: string[];
  eligible_user_ids: string[];
  deadline_hours: number | null;
  escalation_role_key: string | null;
};

export type ApprovalPolicy = {
  id: string;
  policy_id: string;
  organization_id: string;
  workspace_id: string;
  name: string;
  version: number;
  status: "draft" | "published";
  agreement_family: string;
  document_direction: "any" | "first_party" | "counterparty";
  jurisdiction: string;
  materiality: "any" | "low" | "medium" | "high" | "critical";
  precedence: number;
  submitter_may_approve: boolean;
  allow_cross_stage_same_approver: boolean;
  stages: ApprovalPolicyStage[];
  created_at: string;
  published_at: string | null;
};

export type ApprovalPolicyDraft = {
  name: string;
  agreement_family: "client_agreement" | "liquidity_provider_agreement";
  document_direction: "any" | "first_party" | "counterparty";
  jurisdiction: string;
  materiality: "any" | "low" | "medium" | "high" | "critical";
  precedence: number;
  submitter_may_approve: boolean;
  allow_cross_stage_same_approver: boolean;
  stages: ApprovalPolicyStage[];
};

type Options = { scope: AgreementScope; token?: string; baseUrl?: string };
const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function url(baseUrl: string, path: string, scope: AgreementScope): string {
  const query = new URLSearchParams({ organization_id: scope.organizationId, workspace_id: scope.workspaceId });
  return `${baseUrl.replace(/\/$/, "")}${path}?${query}`;
}

function requestHeaders(token?: string, json = false): HeadersInit {
  return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(json ? { "Content-Type": "application/json" } : {}) };
}

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error((await response.text()) || "Approval request failed");
  return response.json() as Promise<T>;
}

export async function listApprovalPolicies({ baseUrl = defaultBaseUrl, scope, token }: Options): Promise<ApprovalPolicy[]> {
  return decode(await fetch(url(baseUrl, "/approval-policies", scope), { cache: "no-store", headers: requestHeaders(token) }));
}

export async function createApprovalPolicy({ baseUrl = defaultBaseUrl, scope, token, draft }: Options & { draft: ApprovalPolicyDraft }): Promise<ApprovalPolicy> {
  return decode(await fetch(url(baseUrl, "/approval-policies", scope), { method: "POST", headers: requestHeaders(token, true), body: JSON.stringify(draft) }));
}

export async function publishApprovalPolicy({ baseUrl = defaultBaseUrl, scope, token, policyId, version }: Options & { policyId: string; version: number }): Promise<ApprovalPolicy> {
  return decode(await fetch(url(baseUrl, `/approval-policies/${policyId}/versions/${version}/publish`, scope), { method: "POST", headers: requestHeaders(token) }));
}

export async function listReviewAssignments({ baseUrl = defaultBaseUrl, scope, token }: Options): Promise<ReviewAssignment[]> {
  return decode(await fetch(url(baseUrl, "/reviews/inbox", scope), { cache: "no-store", headers: requestHeaders(token) }));
}

export async function getReviewNotifications({ baseUrl = defaultBaseUrl, scope, token }: Options): Promise<ReviewNotificationSummary> {
  return decode(await fetch(url(baseUrl, "/reviews/notifications", scope), { cache: "no-store", headers: requestHeaders(token) }));
}

export async function getReview({ baseUrl = defaultBaseUrl, scope, token, reviewId }: Options & { reviewId: string }): Promise<ReviewCase> {
  return decode(await fetch(url(baseUrl, `/reviews/${reviewId}`, scope), { cache: "no-store", headers: requestHeaders(token) }));
}

export async function listReviewComments({ baseUrl = defaultBaseUrl, scope, token, reviewId }: Options & { reviewId: string }): Promise<ReviewComment[]> {
  return decode(await fetch(url(baseUrl, `/reviews/${reviewId}/comments`, scope), { cache: "no-store", headers: requestHeaders(token) }));
}

export async function getReviewWorkflow({ baseUrl = defaultBaseUrl, scope, token, reviewId }: Options & { reviewId: string }): Promise<Record<string, unknown> | null> {
  const response = await fetch(url(baseUrl, `/reviews/${reviewId}/workflow`, scope), { cache: "no-store", headers: requestHeaders(token) });
  if (response.status === 404) return null;
  return decode(response);
}

export async function getFinalReviewPackage({ baseUrl = defaultBaseUrl, scope, token, reviewId }: Options & { reviewId: string }): Promise<Record<string, unknown> | null> {
  const response = await fetch(url(baseUrl, `/reviews/${reviewId}/final-package`, scope), { cache: "no-store", headers: requestHeaders(token) });
  if (response.status === 409 || response.status === 404) return null;
  return decode(response);
}
