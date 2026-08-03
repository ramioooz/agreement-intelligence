"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import type {
  QuestionCitation,
  QuestionThread,
  QuestionTurn,
} from "@/lib/question-api";
import type { SearchResult } from "@/lib/search-api";
import type { SearchFilters } from "@/lib/search-api";

export type QuestionAnswerState = {
  state:
    | "answered"
    | "partial"
    | "insufficient_evidence"
    | "conflicting_evidence"
    | "model_unavailable";
  message: string;
  citations?: QuestionCitation[];
  provenance?: {
    model?: string;
    indexVersion?: string;
  };
};

type SearchWorkspaceProps = {
  initialQuery: string;
  initialFilters?: SearchFilters;
  results?: SearchResult[];
  qaState?: QuestionAnswerState;
  thread?: QuestionThread;
};

function sourceHref(result: SearchResult): string {
  const anchorId = result.navigation.anchor_ids[0];
  return `/dashboard/agreements/${result.navigation.agreement_id}#evidence-${anchorId}`;
}

function stateLabel(state: QuestionAnswerState["state"]): string {
  return state.replaceAll("_", " ");
}

function answerState(turn: QuestionTurn): QuestionAnswerState {
  return {
    state: turn.answer.status,
    message: turn.answer.message,
    citations: turn.answer.claims.flatMap((claim) => claim.citations),
  };
}

function normalizedAgreementIds(value: string): string[] {
  return [
    ...new Set(
      value
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean),
    ),
  ];
}

export function SearchWorkspace({
  initialQuery,
  initialFilters = {},
  results = [],
  qaState,
  thread,
}: SearchWorkspaceProps) {
  const router = useRouter();
  const [query, setQuery] = useState(initialQuery);
  const [agreementType, setAgreementType] = useState(
    initialFilters.agreementType ?? "",
  );
  const [party, setParty] = useState(initialFilters.party ?? "");
  const [status, setStatus] = useState(initialFilters.status ?? "");
  const [updatedAfter, setUpdatedAfter] = useState(
    initialFilters.updatedAfter ?? "",
  );
  const [updatedBefore, setUpdatedBefore] = useState(
    initialFilters.updatedBefore ?? "",
  );
  const [sourceVersion, setSourceVersion] = useState(
    initialFilters.sourceVersion ?? "",
  );
  const [agreementIds, setAgreementIds] = useState(
    initialFilters.agreementIds?.join(", ") ?? "",
  );
  const [question, setQuestion] = useState("");
  const [questionState, setQuestionState] = useState(qaState);
  const [threadId, setThreadId] = useState(thread?.id);
  const [asking, setAsking] = useState(false);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = query.trim();
    const params = new URLSearchParams();
    if (normalized) params.set("q", normalized);
    if (agreementType) params.set("agreement_type", agreementType);
    if (party.trim()) params.set("party", party.trim());
    if (status) params.set("status", status);
    if (updatedAfter) params.set("updated_after", updatedAfter);
    if (updatedBefore) params.set("updated_before", updatedBefore);
    if (sourceVersion.trim())
      params.set("source_version", sourceVersion.trim());
    for (const agreementId of normalizedAgreementIds(agreementIds)) {
      params.append("agreement_id", agreementId);
    }
    setThreadId(undefined);
    setQuestionState(undefined);
    router.push(
      normalized ? `/dashboard/search?${params}` : "/dashboard/search",
    );
  }

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = question.trim();
    if (!normalized || asking) return;
    setAsking(true);
    setQuestionState(undefined);
    try {
      let activeThreadId = threadId;
      if (!activeThreadId) {
        const threadResponse = await fetch("/api/questions/threads", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            agreement_ids: normalizedAgreementIds(agreementIds),
          }),
        });
        if (!threadResponse.ok) throw new Error("thread unavailable");
        const createdThread = (await threadResponse.json()) as Pick<
          QuestionThread,
          "id"
        >;
        activeThreadId = createdThread.id;
        setThreadId(activeThreadId);
      }
      const turnResponse = await fetch(
        `/api/questions/threads/${activeThreadId}/turns`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: normalized }),
        },
      );
      if (!turnResponse.ok) throw new Error("turn unavailable");
      const turn = (await turnResponse.json()) as QuestionTurn;
      setQuestionState(answerState(turn));
      setQuestion("");
      router.push(
        `/dashboard/search?q=${encodeURIComponent(initialQuery)}&thread=${activeThreadId}`,
      );
    } catch {
      setQuestionState({
        state: "model_unavailable",
        message:
          "Question answering is currently unavailable. Search evidence remains available.",
      });
    } finally {
      setAsking(false);
    }
  }

  return (
    <section aria-labelledby="grounded-search-heading" className="space-y-8">
      <div>
        <Link
          className="inline-flex text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-950 hover:underline"
          href="/dashboard"
        >
          Back to dashboard
        </Link>
        <h1
          className="mt-4 text-3xl font-semibold tracking-tight"
          id="grounded-search-heading"
        >
          Grounded search
        </h1>
        <p className="mt-2 text-slate-600">
          Search only agreements you are authorized to access. Results and
          answers link back to their source evidence.
        </p>
      </div>

      <form
        aria-label="Portfolio search"
        className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-2"
        onSubmit={submitSearch}
      >
        <label className="grid gap-1.5 text-sm font-medium">
          Search
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            name="q"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask about termination, liability, or notices"
            type="search"
            value={query}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Agreement type
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => setAgreementType(event.target.value)}
            placeholder="For example, client_agreement"
            value={agreementType}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Party
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => setParty(event.target.value)}
            placeholder="Party name"
            value={party}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Status
          <select
            className="rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => setStatus(event.target.value)}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="expired">Expired</option>
            <option value="terminated">Terminated</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Updated after
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => setUpdatedAfter(event.target.value)}
            type="date"
            value={updatedAfter}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Updated before
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => setUpdatedBefore(event.target.value)}
            type="date"
            value={updatedBefore}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium">
          Source version
          <input
            className="rounded-lg border border-slate-300 px-3 py-2"
            onChange={(event) => setSourceVersion(event.target.value)}
            placeholder="For example, v3"
            value={sourceVersion}
          />
        </label>
        <div className="grid gap-1.5 text-sm font-medium md:col-span-2">
          <label htmlFor="agreement-ids">Agreement IDs</label>
          <input
            aria-describedby="agreement-ids-help"
            className="rounded-lg border border-slate-300 px-3 py-2"
            id="agreement-ids"
            onChange={(event) => setAgreementIds(event.target.value)}
            placeholder="Comma-separated agreement IDs"
            value={agreementIds}
          />
          <span
            className="text-xs font-normal text-slate-600"
            id="agreement-ids-help"
          >
            Optional. Limit results to specific authorized agreements.
          </span>
        </div>
        <button
          className="w-fit rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
          type="submit"
        >
          Search
        </button>
      </form>

      {initialQuery && results.length === 0 ? (
        <p
          className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-slate-600"
          role="status"
        >
          No authorized evidence matched this search. Try different terms or
          broaden the agreement filters.
        </p>
      ) : null}

      {results.length > 0 ? (
        <section aria-labelledby="search-results-heading" className="space-y-4">
          <h2 className="text-xl font-semibold" id="search-results-heading">
            Search results
          </h2>
          <ol className="space-y-4">
            {results.map((result) => (
              <li
                className="rounded-2xl border border-slate-200 bg-white p-5"
                key={result.citation.chunk_id}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="font-semibold">{result.agreement_title}</h3>
                    <p className="text-sm text-slate-600">
                      {result.agreement_type} · {result.agreement_status}
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                    {result.semantic_rank === null
                      ? "Lexical match"
                      : "Hybrid match"}
                  </span>
                </div>
                <p className="mt-3 text-sm leading-6 text-slate-700">
                  {result.content_preview}
                </p>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <Link
                    className="text-sm font-semibold underline underline-offset-4"
                    href={sourceHref(result)}
                  >
                    View source evidence
                  </Link>
                  <p
                    aria-label={`Index: ${result.index_provenance.embedding_index_version ?? "lexical only"}`}
                    className="text-xs text-slate-500"
                  >
                    Index:{" "}
                    {result.index_provenance.embedding_index_version ??
                      "lexical only"}
                    {" · "}Chunker: {result.index_provenance.chunker_version}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section
        aria-labelledby="reviewer-approved-heading"
        className="rounded-2xl border border-slate-200 bg-white p-5"
      >
        <h2 className="text-xl font-semibold" id="reviewer-approved-heading">
          Reviewer-approved information
        </h2>
        <p className="mt-1 text-sm text-slate-600" role="status">
          No reviewer-approved information is available for this search yet.
          Approval decisions will appear here when the review workflow is
          delivered in Sprint 6.
        </p>
      </section>

      <section
        aria-labelledby="question-answer-heading"
        className="rounded-2xl border border-slate-200 bg-white p-5"
      >
        <h2 className="text-xl font-semibold" id="question-answer-heading">
          Cited Q&amp;A
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Answers are limited to current, authorized retrieval evidence. If the
          evidence is insufficient or conflicting, the application will say so.
        </p>
        <form className="mt-4 grid gap-3" onSubmit={submitQuestion}>
          <label className="grid gap-1.5 text-sm font-medium">
            Question
            <textarea
              className="min-h-24 rounded-lg border border-slate-300 px-3 py-2"
              disabled={!initialQuery || asking}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a question about the retrieved agreements"
              value={question}
            />
          </label>
          <button
            className="w-fit rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!initialQuery || !question.trim() || asking}
            type="submit"
          >
            {asking ? "Answering…" : "Ask question"}
          </button>
        </form>
        {questionState ? (
          <div
            className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4"
            role={questionState.state === "answered" ? "status" : "alert"}
          >
            <p className="font-semibold capitalize">
              {stateLabel(questionState.state)}
            </p>
            <p className="mt-1 text-sm text-slate-700">
              {questionState.message}
            </p>
            {questionState.citations?.length ? (
              <ul className="mt-3 space-y-2">
                {questionState.citations.map((citation) => (
                  <li key={`${citation.agreement_id}-${citation.anchor_id}`}>
                    <Link
                      className="text-sm font-semibold underline underline-offset-4"
                      href={`/dashboard/agreements/${citation.agreement_id}#evidence-${citation.anchor_id}`}
                    >
                      View source evidence
                    </Link>
                    <p className="text-xs text-slate-500">
                      Source version {citation.source_version} ·{" "}
                      {citation.source_checksum}
                    </p>
                  </li>
                ))}
              </ul>
            ) : null}
            {questionState.provenance ? (
              <p className="mt-3 text-xs text-slate-500">
                {questionState.provenance.model
                  ? `Model: ${questionState.provenance.model}`
                  : "Model response unavailable"}
                {questionState.provenance.indexVersion
                  ? ` · Index: ${questionState.provenance.indexVersion}`
                  : ""}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-600">
            Ask a question after you run a search. Your conversation will be
            retained with its cited answer history.
          </p>
        )}
      </section>
    </section>
  );
}
