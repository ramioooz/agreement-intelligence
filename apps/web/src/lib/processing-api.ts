import { ApiRequestError, type AgreementScope } from "@/lib/agreement-api";

export type ProcessingJob = {
  id: string;
  agreement_id: string;
  state: "queued" | "processing" | "completed" | "failed";
  attempt_count: number;
  failure_category: string | null;
  failure_message: string | null;
  next_retry_at: string | null;
  queued_at: string;
  processing_started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  created_at: string;
  updated_at: string;
  retry_permitted: boolean;
};

type ProcessingOptions = {
  baseUrl?: string;
  token?: string;
  scope: AgreementScope;
  agreementId: string;
  jobId: string;
  fetcher?: typeof fetch;
};

type SubmitProcessingOptions = Omit<ProcessingOptions, "jobId"> & {
  idempotencyKey: string;
  profile?: string;
};

const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function jobEndpoint({
  scope,
  agreementId,
  jobId,
  baseUrl,
}: Required<Pick<ProcessingOptions, "scope" | "agreementId" | "jobId">> & {
  baseUrl: string;
}): string {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
  return `${baseUrl.replace(/\/$/, "")}/agreements/${agreementId}/processing-jobs/${jobId}?${params}`;
}

function retryEndpoint(options: Parameters<typeof jobEndpoint>[0]): string {
  return jobEndpoint(options).replace("?", "/retry?");
}

function requeueEndpoint(options: Parameters<typeof jobEndpoint>[0]): string {
  return jobEndpoint(options).replace("?", "/requeue?");
}

function processingCollectionEndpoint({
  scope,
  agreementId,
  baseUrl,
}: Omit<Parameters<typeof jobEndpoint>[0], "jobId">): string {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
  return `${baseUrl.replace(/\/$/, "")}/agreements/${agreementId}/processing-jobs?${params}`;
}

export async function submitProcessingJob({
  baseUrl = defaultBaseUrl,
  token,
  scope,
  agreementId,
  idempotencyKey,
  profile = "baseline",
  fetcher = fetch,
}: SubmitProcessingOptions): Promise<ProcessingJob> {
  const response = await fetcher(
    processingCollectionEndpoint({ baseUrl, scope, agreementId }),
    {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({ profile }),
    },
  );
  if (!response.ok) {
    throw new ApiRequestError(
      "Processing submission could not be completed.",
      response.status,
    );
  }
  return response.json() as Promise<ProcessingJob>;
}

export async function getProcessingJob({
  baseUrl = defaultBaseUrl,
  token,
  scope,
  agreementId,
  jobId,
  fetcher = fetch,
}: ProcessingOptions): Promise<ProcessingJob> {
  const response = await fetcher(
    jobEndpoint({ baseUrl, scope, agreementId, jobId }),
    {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!response.ok) {
    throw new ApiRequestError(
      "Processing status could not be loaded.",
      response.status,
    );
  }
  return response.json() as Promise<ProcessingJob>;
}

export async function retryProcessingJob({
  baseUrl = defaultBaseUrl,
  token,
  scope,
  agreementId,
  jobId,
  fetcher = fetch,
}: ProcessingOptions): Promise<ProcessingJob> {
  const response = await fetcher(
    retryEndpoint({ baseUrl, scope, agreementId, jobId }),
    {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!response.ok) {
    throw new ApiRequestError(
      "Processing retry could not be completed.",
      response.status,
    );
  }
  return response.json() as Promise<ProcessingJob>;
}

export async function requeueProcessingJob({
  baseUrl = defaultBaseUrl,
  token,
  scope,
  agreementId,
  jobId,
  fetcher = fetch,
}: ProcessingOptions): Promise<ProcessingJob> {
  const response = await fetcher(
    requeueEndpoint({ baseUrl, scope, agreementId, jobId }),
    {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!response.ok) {
    throw new ApiRequestError(
      "Processing requeue could not be completed.",
      response.status,
    );
  }
  return response.json() as Promise<ProcessingJob>;
}
