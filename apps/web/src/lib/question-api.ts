import type { AgreementScope } from "@/lib/agreement-api";

export type QuestionCitation = {
  anchor_id: string;
  supporting_quote: string;
  agreement_id: string;
  source_checksum: string;
  source_version: string;
};

export type QuestionAnswer = {
  status:
    | "answered"
    | "partial"
    | "insufficient_evidence"
    | "conflicting_evidence"
    | "model_unavailable";
  message: string;
  claims: Array<{
    text: string;
    citations: QuestionCitation[];
  }>;
};

export type QuestionTurn = {
  id: string;
  question: string;
  answer: QuestionAnswer;
  created_at: string;
};

export type QuestionThread = {
  id: string;
  organization_id: string;
  workspace_id: string;
  agreement_ids: string[] | null;
  turns: QuestionTurn[];
};

type ClientOptions = {
  scope: AgreementScope;
  token?: string;
  baseUrl?: string;
  fetcher?: typeof fetch;
};

const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

function endpoint(
  baseUrl: string,
  path: string,
  scope: AgreementScope,
): string {
  const query = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
  });
  return `${baseUrl.replace(/\/$/, "")}${path}?${query}`;
}

function headers(token: string | undefined): HeadersInit {
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function decode<T>(response: Response): Promise<T> {
  if (!response.ok)
    throw new Error("Question answering is currently unavailable.");
  return response.json() as Promise<T>;
}

export async function createQuestionThread({
  scope,
  token,
  baseUrl = defaultBaseUrl,
  fetcher = fetch,
  agreementIds,
}: ClientOptions & { agreementIds?: string[] }): Promise<QuestionThread> {
  return decode<QuestionThread>(
    await fetcher(endpoint(baseUrl, "/questions/threads", scope), {
      method: "POST",
      headers: headers(token),
      body: JSON.stringify(
        agreementIds?.length ? { agreement_ids: agreementIds } : {},
      ),
    }),
  );
}

export async function getQuestionThread({
  scope,
  token,
  baseUrl = defaultBaseUrl,
  fetcher = fetch,
  threadId,
}: ClientOptions & { threadId: string }): Promise<QuestionThread> {
  return decode<QuestionThread>(
    await fetcher(endpoint(baseUrl, `/questions/threads/${threadId}`, scope), {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }),
  );
}

export async function askQuestion({
  scope,
  token,
  baseUrl = defaultBaseUrl,
  fetcher = fetch,
  threadId,
  question,
}: ClientOptions & {
  threadId: string;
  question: string;
}): Promise<QuestionTurn> {
  return decode<QuestionTurn>(
    await fetcher(
      endpoint(baseUrl, `/questions/threads/${threadId}/turns`, scope),
      {
        method: "POST",
        headers: headers(token),
        body: JSON.stringify({ question }),
      },
    ),
  );
}
