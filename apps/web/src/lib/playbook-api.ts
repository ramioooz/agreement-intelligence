import { ApiRequestError, type AgreementScope } from "@/lib/agreement-api";

export type PlaybookStatus = "draft" | "published" | "archived";
export type PlaybookDocumentDirection = "any" | "first_party" | "counterparty";
export type PlaybookPolicyType = "required" | "prohibited" | "preferred";
export type PlaybookSeverity = "low" | "medium" | "high" | "critical";

export type PlaybookRuleWrite = {
  clause_type: string;
  title: string;
  policy_type: PlaybookPolicyType;
  preferred_language: string | null;
  fallback_language: string | null;
  severity: PlaybookSeverity;
  legal_rationale: string;
  reviewer_guidance: string;
  evaluation_config: {
    method: "deterministic" | "semantic";
    semantic_assessment_permitted: boolean;
  };
};

export type PlaybookRule = PlaybookRuleWrite & { id: string };

export type PlaybookVersion = {
  id: string;
  playbook_id: string;
  organization_id: string;
  workspace_id: string;
  name: string;
  version: number;
  status: PlaybookStatus;
  agreement_family: string;
  document_direction: PlaybookDocumentDirection;
  jurisdiction: string;
  priority: number;
  rules: PlaybookRule[];
  audit_events: Array<{
    action: string;
    actor_id: string;
    occurred_at: string;
    metadata: Record<string, unknown>;
  }>;
  created_at: string;
  published_at: string | null;
  archived_at: string | null;
};

type ClientOptions = {
  baseUrl?: string;
  token?: string;
  fetcher?: typeof fetch;
};

type ScopedOptions = ClientOptions & { scope: AgreementScope };

const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function endpoint(
  baseUrl: string,
  path: string,
  scope: AgreementScope,
  extra?: Record<string, string>,
): string {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
    ...extra,
  });
  return `${baseUrl.replace(/\/$/, "")}${path}?${params}`;
}

function headers(token: string | undefined): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string };
      message?: string;
    } | null;
    const message =
      body?.message ??
      (typeof body?.detail === "string"
        ? body.detail
        : body?.detail?.message) ??
      "The playbook request could not be completed.";
    throw new ApiRequestError(message, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function listPlaybooks({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  agreementFamily,
  fetcher = fetch,
}: ScopedOptions & { agreementFamily?: string }): Promise<PlaybookVersion[]> {
  return request<PlaybookVersion[]>(
    await fetcher(
      endpoint(baseUrl, "/playbooks", scope, {
        ...(agreementFamily ? { agreement_family: agreementFamily } : {}),
      }),
      { cache: "no-store", headers: headers(token) },
    ),
  );
}

export async function createPlaybook({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  name,
  agreementFamily,
  documentDirection = "any",
  jurisdiction = "any",
  priority = 100,
  fetcher = fetch,
}: ScopedOptions & {
  name: string;
  agreementFamily: string;
  documentDirection?: PlaybookDocumentDirection;
  jurisdiction?: string;
  priority?: number;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(endpoint(baseUrl, "/playbooks", scope), {
      method: "POST",
      headers: { ...headers(token), "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        agreement_family: agreementFamily,
        document_direction: documentDirection,
        jurisdiction,
        priority,
      }),
    }),
  );
}

export async function createPlaybookVersion({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  sourceVersion,
  fetcher = fetch,
}: ScopedOptions & {
  playbookId: string;
  sourceVersion?: number;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(
      endpoint(baseUrl, `/playbooks/${playbookId}/versions`, scope),
      {
        method: "POST",
        headers: { ...headers(token), "Content-Type": "application/json" },
        body: JSON.stringify({ source_version: sourceVersion }),
      },
    ),
  );
}

export async function addPlaybookRule({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  version,
  rule,
  fetcher = fetch,
}: ScopedOptions & {
  playbookId: string;
  version: number;
  rule: PlaybookRuleWrite;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(
      endpoint(
        baseUrl,
        `/playbooks/${playbookId}/versions/${version}/rules`,
        scope,
      ),
      {
        method: "POST",
        headers: { ...headers(token), "Content-Type": "application/json" },
        body: JSON.stringify(rule),
      },
    ),
  );
}

export async function updatePlaybookRule({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  version,
  ruleId,
  rule,
  fetcher = fetch,
}: ScopedOptions & {
  playbookId: string;
  version: number;
  ruleId: string;
  rule: PlaybookRuleWrite;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(
      endpoint(
        baseUrl,
        `/playbooks/${playbookId}/versions/${version}/rules/${ruleId}`,
        scope,
      ),
      {
        method: "PUT",
        headers: { ...headers(token), "Content-Type": "application/json" },
        body: JSON.stringify(rule),
      },
    ),
  );
}

export async function deletePlaybookRule({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  version,
  ruleId,
  fetcher = fetch,
}: ScopedOptions & {
  playbookId: string;
  version: number;
  ruleId: string;
}): Promise<void> {
  const response = await fetcher(
    endpoint(
      baseUrl,
      `/playbooks/${playbookId}/versions/${version}/rules/${ruleId}`,
      scope,
      { confirm: "true" },
    ),
    { method: "DELETE", headers: headers(token) },
  );
  if (!response.ok) await request<never>(response);
}

export async function publishPlaybookVersion({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  version,
  fetcher = fetch,
}: ScopedOptions & {
  playbookId: string;
  version: number;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(
      endpoint(
        baseUrl,
        `/playbooks/${playbookId}/versions/${version}/publish`,
        scope,
      ),
      { method: "POST", headers: headers(token) },
    ),
  );
}

export async function archivePlaybook({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  reason,
  fetcher = fetch,
}: ScopedOptions & {
  playbookId: string;
  reason: string;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(
      endpoint(baseUrl, `/playbooks/${playbookId}/archive`, scope, { reason }),
      { method: "POST", headers: headers(token) },
    ),
  );
}

export async function listEligiblePlaybooks({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  agreementId,
  fetcher = fetch,
}: ScopedOptions & { agreementId: string }): Promise<PlaybookVersion[]> {
  return request<PlaybookVersion[]>(
    await fetcher(
      endpoint(baseUrl, "/playbooks/eligible", scope, {
        agreement_id: agreementId,
      }),
      {
        cache: "no-store",
        headers: headers(token),
      },
    ),
  );
}

export async function recordPlaybookOverride({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  agreementId,
  playbookVersionId,
  reason,
  fetcher = fetch,
}: ScopedOptions & {
  agreementId: string;
  playbookVersionId: string;
  reason: string;
}): Promise<PlaybookVersion> {
  return request<PlaybookVersion>(
    await fetcher(endpoint(baseUrl, "/playbooks/overrides", scope), {
      method: "POST",
      headers: { ...headers(token), "Content-Type": "application/json" },
      body: JSON.stringify({
        agreement_id: agreementId,
        playbook_version_id: playbookVersionId,
        reason,
      }),
    }),
  );
}

export async function deletePlaybook({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  playbookId,
  reason,
  fetcher = fetch,
}: ScopedOptions & { playbookId: string; reason: string }): Promise<void> {
  const response = await fetcher(
    endpoint(baseUrl, `/playbooks/${playbookId}`, scope, {
      confirm: "true",
      reason,
    }),
    { method: "DELETE", headers: headers(token) },
  );
  if (!response.ok) await request<never>(response);
}
