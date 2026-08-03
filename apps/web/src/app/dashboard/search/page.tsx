import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { SearchWorkspace } from "@/components/search-workspace";
import { type AgreementScope } from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import { getQuestionThread, type QuestionThread } from "@/lib/question-api";
import {
  searchAgreements,
  type SearchFilters,
  type SearchResult,
} from "@/lib/search-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

function stringParam(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function searchFiltersFromParams(params: {
  agreement_type?: string | string[];
  party?: string | string[];
  status?: string | string[];
  updated_after?: string | string[];
  updated_before?: string | string[];
  source_version?: string | string[];
  agreement_id?: string | string[];
}): SearchFilters {
  const agreementIds = (
    Array.isArray(params.agreement_id)
      ? params.agreement_id
      : params.agreement_id
        ? [params.agreement_id]
        : []
  ).filter((value) => value.trim());
  return {
    agreementType: stringParam(params.agreement_type),
    party: stringParam(params.party),
    status: stringParam(params.status),
    updatedAfter: stringParam(params.updated_after),
    updatedBefore: stringParam(params.updated_before),
    sourceVersion: stringParam(params.source_version),
    agreementIds: agreementIds.length ? agreementIds : undefined,
  };
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{
    q?: string | string[];
    thread?: string | string[];
    agreement_type?: string | string[];
    party?: string | string[];
    status?: string | string[];
    updated_after?: string | string[];
    updated_before?: string | string[];
    source_version?: string | string[];
    agreement_id?: string | string[];
  }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const params = await searchParams;
  const query = stringParam(params.q) ?? "";
  const filters = searchFiltersFromParams(params);
  const scope = scopeFromEnvironment();
  let results: SearchResult[] = [];
  let thread: QuestionThread | undefined;
  const token = await getKeycloakAccessToken(await headers());

  if (scope && query) {
    try {
      results = (
        await searchAgreements({
          scope,
          query,
          filters,
          token,
        })
      ).items;
    } catch {
      results = [];
    }
  }

  const threadId = stringParam(params.thread);
  if (scope && threadId) {
    try {
      thread = await getQuestionThread({
        scope,
        threadId,
        token,
      });
    } catch {
      thread = undefined;
    }
  }

  const latestTurn = thread?.turns.at(-1);
  const qaState = latestTurn
    ? {
        state: latestTurn.answer.status,
        message: latestTurn.answer.message,
        citations: latestTurn.answer.claims.flatMap((claim) => claim.citations),
      }
    : undefined;

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <SearchWorkspace
        initialQuery={query}
        initialFilters={filters}
        qaState={qaState}
        results={results}
        thread={thread}
      />
    </main>
  );
}
