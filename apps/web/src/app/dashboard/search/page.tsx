import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { SearchWorkspace } from "@/components/search-workspace";
import { type AgreementScope } from "@/lib/agreement-api";
import { getKeycloakAccessToken } from "@/lib/auth-session-token";
import { getQuestionThread, type QuestionThread } from "@/lib/question-api";
import { searchAgreements, type SearchResult } from "@/lib/search-api";

function scopeFromEnvironment(): AgreementScope | null {
  const organizationId = process.env.API_ORGANIZATION_ID;
  const workspaceId = process.env.API_WORKSPACE_ID;
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; thread?: string }>;
}) {
  if (!(await auth())?.user) redirect("/sign-in");
  const params = await searchParams;
  const query = params.q?.trim() ?? "";
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
          token,
        })
      ).items;
    } catch {
      results = [];
    }
  }

  if (scope && params.thread) {
    try {
      thread = await getQuestionThread({
        scope,
        threadId: params.thread,
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
        citations: latestTurn.answer.claims.flatMap((claim) =>
          claim.citations.flatMap((citation) =>
            citation.agreement_id
              ? [
                  {
                    agreementId: citation.agreement_id,
                    anchorId: citation.anchor_id,
                    label: "View source evidence",
                  },
                ]
              : [],
          ),
        ),
      }
    : undefined;

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <SearchWorkspace
        initialQuery={query}
        qaState={qaState}
        results={results}
        thread={thread}
      />
    </main>
  );
}
