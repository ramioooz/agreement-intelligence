export type AgreementStatus = "draft" | "active" | "expired" | "terminated";
export type ProcessingState =
  "pending" | "queued" | "processing" | "completed" | "failed";

export type AgreementScope = {
  organizationId: string;
  workspaceId: string;
};

export type AgreementFile = {
  file_name: string;
  content_type: string;
  storage_key: string;
  checksum: string;
  byte_size: number;
  version_number: number;
};

export type AgreementSummary = {
  id: string;
  organization_id: string;
  workspace_id: string;
  title: string;
  agreement_type: string;
  status: AgreementStatus;
  parties: Array<{ name: string; role: string }>;
  files: AgreementFile[];
  processing_state: ProcessingState;
  audit_metadata: Record<string, string>;
  audit_events: Array<{
    action: "created" | "archived" | "restored";
    actor_id: string;
    occurred_at: string;
  }>;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AgreementPage = {
  items: AgreementSummary[];
  page: { limit: number; next_cursor: string | null };
};

export type DocumentAnalysis = {
  schema_version: string;
  pipeline_version: string;
  diagnostics: Array<{ code: string; message: string; page_numbers: number[] }>;
  classification: {
    family:
      | "client_agreement"
      | "liquidity_provider_agreement"
      | "unknown_needs_review";
    confidence: number;
    rationale: string;
    version: string;
    evidence_terms: string[];
  } | null;
  clauses: Array<{
    category: string;
    source_text: string;
    citation_anchor_ids: string[];
    confidence: number;
    extraction_version: string;
  }>;
  risks?: Array<{
    severity: "low" | "medium" | "high" | "critical";
    explanation: string;
    citation_anchor_ids: string[];
  }>;
  analysis_provenance?: {
    mode: "deterministic" | "hybrid";
    model?: string;
    fallback_reason?: string;
  };
  summaries: Record<
    string,
    {
      version: string;
      claims: Array<{ text: string; citation_anchor_ids: string[] }>;
    }
  >;
  document: {
    pages: Array<{
      number: number;
      blocks: Array<{ anchor_id: string; kind: string; text: string }>;
    }>;
  };
};

export type UploadedDocument = {
  document_id: string;
  tenant_id: string;
  workspace_id: string;
  original_filename: string;
  content_type: string;
  byte_size: number;
  sha256: string;
  object_key: string;
  duplicate: boolean;
};

export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

type ClientOptions = {
  baseUrl?: string;
  token?: string;
  fetcher?: typeof fetch;
};

type ListAgreementsOptions = ClientOptions & {
  scope: AgreementScope;
  query?: string;
  status?: AgreementStatus;
  agreementType?: string;
  cursor?: string;
  limit?: number;
};

type GetAgreementOptions = ClientOptions & {
  scope: AgreementScope;
  agreementId: string;
};

type UploadDocumentOptions = ClientOptions & {
  scope: AgreementScope;
  file: File;
};

type CreateAgreementOptions = ClientOptions & {
  scope: AgreementScope;
  agreement: Omit<
    AgreementSummary,
    | "id"
    | "organization_id"
    | "workspace_id"
    | "audit_events"
    | "archived_at"
    | "created_at"
    | "updated_at"
  >;
};

const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function authorizationHeader(token: string | undefined): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function scopedParams(scope: AgreementScope): URLSearchParams {
  return new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
}

function endpoint(
  baseUrl: string,
  path: string,
  params?: URLSearchParams,
): string {
  const query = params?.toString();
  return `${baseUrl.replace(/\/$/, "")}${path}${query ? `?${query}` : ""}`;
}

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      message?: string;
      detail?: string;
    } | null;
    throw new ApiRequestError(
      payload?.message ??
        payload?.detail ??
        "The request could not be completed.",
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export async function listAgreements({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  query,
  status,
  agreementType,
  cursor,
  limit = 25,
  fetcher = fetch,
}: ListAgreementsOptions): Promise<AgreementPage> {
  const params = scopedParams(scope);
  params.set("limit", String(limit));
  if (cursor) params.set("cursor", cursor);
  if (status) params.set("status", status);
  if (query) params.set("query", query);
  if (agreementType) params.set("agreement_type", agreementType);

  return decode<AgreementPage>(
    await fetcher(endpoint(baseUrl, "/agreements", params), {
      cache: "no-store",
      headers: authorizationHeader(token),
    }),
  );
}

export async function getAgreement({
  baseUrl = defaultBaseUrl,
  scope,
  agreementId,
  token,
  fetcher = fetch,
}: GetAgreementOptions): Promise<AgreementSummary> {
  return decode<AgreementSummary>(
    await fetcher(
      endpoint(baseUrl, `/agreements/${agreementId}`, scopedParams(scope)),
      {
        cache: "no-store",
        headers: authorizationHeader(token),
      },
    ),
  );
}

export async function getDocumentAnalysis({
  baseUrl = defaultBaseUrl,
  scope,
  agreementId,
  token,
  fetcher = fetch,
}: GetAgreementOptions): Promise<DocumentAnalysis> {
  return decode<DocumentAnalysis>(
    await fetcher(
      endpoint(
        baseUrl,
        `/agreements/${agreementId}/analysis`,
        scopedParams(scope),
      ),
      { cache: "no-store", headers: authorizationHeader(token) },
    ),
  );
}

export async function uploadDocument({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  file,
  fetcher = fetch,
}: UploadDocumentOptions): Promise<UploadedDocument> {
  const form = new FormData();
  form.set("organization_id", scope.organizationId);
  form.set("workspace_id", scope.workspaceId);
  form.set("file", file);

  return decode<UploadedDocument>(
    await fetcher(endpoint(baseUrl, "/documents"), {
      method: "POST",
      headers: authorizationHeader(token),
      body: form,
    }),
  );
}

export async function createAgreement({
  baseUrl = defaultBaseUrl,
  scope,
  token,
  agreement,
  fetcher = fetch,
}: CreateAgreementOptions): Promise<AgreementSummary> {
  return decode<AgreementSummary>(
    await fetcher(endpoint(baseUrl, "/agreements", scopedParams(scope)), {
      method: "POST",
      headers: {
        ...authorizationHeader(token),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(agreement),
    }),
  );
}

export async function deleteAgreement({
  baseUrl = defaultBaseUrl,
  scope,
  agreementId,
  token,
  fetcher = fetch,
}: GetAgreementOptions): Promise<void> {
  const response = await fetcher(
    endpoint(baseUrl, `/agreements/${agreementId}`, scopedParams(scope)),
    { method: "DELETE", headers: authorizationHeader(token) },
  );
  if (!response.ok) {
    throw new ApiRequestError(
      "The agreement could not be deleted.",
      response.status,
    );
  }
}

export function documentDownloadPath({
  scope,
  objectKey,
}: {
  scope: AgreementScope;
  objectKey: string;
}): string {
  const params = scopedParams(scope);
  params.set("object_key", objectKey);
  return `/api/documents/download?${params}`;
}
