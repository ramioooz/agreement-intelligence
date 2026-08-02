"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import {
  findingResultLabel,
  ReviewFindingList,
} from "@/components/review-finding-list";
import type { PlaybookFindingResponse } from "@/lib/review-api";

export type ReviewEvidence = {
  citationId: string;
  kind: string;
  pageNumber: number;
  text: string;
};

type ReviewWorkspaceProps = {
  agreementId: string;
  agreementTitle: string;
  findings?: PlaybookFindingResponse[];
  evidence?: ReviewEvidence[];
  documentUrl?: string;
  state?: "loading" | "error";
};

function label(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

const severityOrder: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function compareFindings(
  left: PlaybookFindingResponse,
  right: PlaybookFindingResponse,
): number {
  return (
    (severityOrder[left.severity] ?? 4) -
      (severityOrder[right.severity] ?? 4) ||
    left.clause_type.localeCompare(right.clause_type) ||
    left.rule_title.localeCompare(right.rule_title) ||
    left.id.localeCompare(right.id)
  );
}

export function ReviewWorkspace({
  agreementId,
  agreementTitle,
  findings = [],
  evidence = [],
  documentUrl,
  state,
}: ReviewWorkspaceProps) {
  const [severity, setSeverity] = useState("all");
  const [status, setStatus] = useState("all");
  const [selectedFindingId, setSelectedFindingId] = useState<string>();
  const sortedFindings = useMemo(
    () => [...findings].sort(compareFindings),
    [findings],
  );
  const filteredFindings = useMemo(
    () =>
      sortedFindings.filter(
        (finding) =>
          (severity === "all" || finding.severity === severity) &&
          (status === "all" || finding.result === status),
      ),
    [sortedFindings, severity, status],
  );
  const selectedFinding =
    filteredFindings.find((finding) => finding.id === selectedFindingId) ??
    filteredFindings[0];
  const selectedEvidence = selectedFinding
    ? evidence.filter((item) =>
        selectedFinding.citation_ids.includes(item.citationId),
      )
    : [];
  const severities = [
    ...new Set(sortedFindings.map((finding) => finding.severity)),
  ];
  const statuses = [
    ...new Set(sortedFindings.map((finding) => finding.result)),
  ];

  if (state === "loading") {
    return (
      <p
        className="rounded-xl border border-slate-200 bg-white p-6 text-slate-600"
        role="status"
      >
        Loading review findings…
      </p>
    );
  }
  if (state === "error") {
    return (
      <p
        className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-900"
        role="alert"
      >
        Unable to load the legal review workspace. Check your access and try
        again.
      </p>
    );
  }

  return (
    <section aria-labelledby="review-workspace-heading" className="space-y-6">
      <header>
        <Link
          className="text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-950 hover:underline"
          href={`/dashboard/agreements/${agreementId}`}
        >
          Back to agreement
        </Link>
        <p className="mt-5 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Legal review
        </p>
        <h1
          className="mt-2 text-3xl font-semibold tracking-tight"
          id="review-workspace-heading"
        >
          {agreementTitle}
        </h1>
        <p className="mt-2 text-slate-600">
          Review playbook findings alongside their cited source evidence.
        </p>
      </header>

      <nav aria-label="Review workspace sections">
        <ul className="flex flex-wrap gap-4 text-sm font-semibold">
          <li>
            <a className="underline" href="#findings">
              Findings
            </a>
          </li>
          <li>
            <a
              className="underline"
              href={
                selectedFinding ? `#finding-${selectedFinding.id}` : "#findings"
              }
            >
              Finding detail
            </a>
          </li>
          <li>
            <a className="underline" href="#source-evidence">
              Source evidence
            </a>
          </li>
        </ul>
      </nav>

      {sortedFindings.length ? (
        <nav
          aria-label="Clause review outline"
          className="rounded-2xl border border-slate-200 bg-white p-4"
        >
          <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Clause outline
          </p>
          <ol className="mt-3 grid gap-2 sm:grid-cols-2">
            {sortedFindings.map((finding) => (
              <li key={finding.id}>
                <a
                  aria-label={`${label(finding.clause_type)} — ${finding.rule_title}`}
                  aria-current={
                    selectedFinding?.id === finding.id ? "true" : undefined
                  }
                  className="block rounded-lg border border-slate-200 px-3 py-2 text-sm hover:border-slate-400 aria-current:border-slate-950 aria-current:bg-slate-50"
                  href={`#finding-${finding.id}`}
                  onClick={() => {
                    setSeverity("all");
                    setStatus("all");
                    setSelectedFindingId(finding.id);
                  }}
                >
                  <span className="block font-semibold">
                    {label(finding.clause_type)} — {finding.rule_title}
                  </span>
                  <span className="mt-1 block text-slate-600">
                    {finding.reviewer_guidance ||
                      "No reviewer guidance is recorded for this rule."}
                  </span>
                </a>
              </li>
            ))}
          </ol>
        </nav>
      ) : null}

      {findings.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-slate-600">
          No playbook findings are available for this agreement.
        </p>
      ) : (
        <>
          <fieldset className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-4 sm:grid-cols-2">
            <legend className="px-1 font-semibold">Filter findings</legend>
            <label className="grid gap-1.5 text-sm font-medium">
              Severity
              <select
                className="rounded-lg border border-slate-300 px-3 py-2"
                onChange={(event) => {
                  setSeverity(event.target.value);
                  setSelectedFindingId(undefined);
                }}
                value={severity}
              >
                <option value="all">All severities</option>
                {severities.map((item) => (
                  <option key={item} value={item}>
                    {label(item)}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">
              Finding status
              <select
                className="rounded-lg border border-slate-300 px-3 py-2"
                onChange={(event) => {
                  setStatus(event.target.value);
                  setSelectedFindingId(undefined);
                }}
                value={status}
              >
                <option value="all">All statuses</option>
                {statuses.map((item) => (
                  <option key={item} value={item}>
                    {findingResultLabel(item)}
                  </option>
                ))}
              </select>
            </label>
          </fieldset>

          <div className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
            <section
              aria-labelledby="findings-heading"
              className="rounded-2xl border border-slate-200 bg-slate-50 p-5"
              id="findings"
            >
              <h2 className="text-xl font-semibold" id="findings-heading">
                Findings
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                {filteredFindings.length} of {findings.length} shown
              </p>
              {filteredFindings.length ? (
                <ReviewFindingList
                  findings={filteredFindings}
                  onSelect={setSelectedFindingId}
                  selectedFindingId={selectedFinding?.id}
                />
              ) : (
                <p className="mt-4 text-sm text-slate-600">
                  No findings match the selected filters.
                </p>
              )}
            </section>

            <div className="space-y-6">
              {selectedFinding ? (
                <article
                  aria-labelledby="finding-detail-heading"
                  className="rounded-2xl border border-slate-200 bg-white p-5"
                  id={`finding-${selectedFinding.id}`}
                >
                  <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                    {label(selectedFinding.clause_type)} ·{" "}
                    {label(selectedFinding.severity)} severity ·{" "}
                    {findingResultLabel(selectedFinding.result)}
                  </p>
                  <h2
                    className="mt-2 text-xl font-semibold"
                    id="finding-detail-heading"
                  >
                    {selectedFinding.rule_title}
                  </h2>
                  <p className="mt-2 text-sm text-slate-600">
                    Confidence {Math.round(selectedFinding.confidence * 100)}% ·{" "}
                    {selectedFinding.method === "deterministic"
                      ? "Deterministic policy evaluation"
                      : "Semantic evaluation"}
                  </p>

                  <section
                    className="mt-5"
                    aria-labelledby="reviewer-guidance-heading"
                  >
                    <h3
                      className="font-semibold"
                      id="reviewer-guidance-heading"
                    >
                      Reviewer guidance
                    </h3>
                    <p className="mt-2 text-sm text-slate-700">
                      {selectedFinding.reviewer_guidance ||
                        "No reviewer guidance is recorded for this rule."}
                    </p>
                  </section>

                  <section
                    className="mt-5"
                    aria-labelledby="policy-rationale-heading"
                  >
                    <h3 className="font-semibold" id="policy-rationale-heading">
                      Policy rationale
                    </h3>
                    <p className="mt-2 text-sm text-slate-700">
                      {selectedFinding.risk.risk_rationale}
                    </p>
                  </section>

                  {selectedFinding.risk.model_explanation ? (
                    <section
                      aria-labelledby="model-explanation-heading"
                      className="mt-5 rounded-xl border border-sky-200 bg-sky-50 p-4"
                    >
                      <h3
                        className="font-semibold"
                        id="model-explanation-heading"
                      >
                        Optional model explanation
                      </h3>
                      <p className="mt-2 text-sm text-slate-700">
                        {selectedFinding.risk.model_explanation}
                      </p>
                    </section>
                  ) : null}

                  {selectedFinding.fallback_suggestions.map((suggestion) => (
                    <section
                      aria-labelledby={`suggestion-${suggestion.rule_id}`}
                      className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4"
                      key={`${suggestion.rule_id}-${suggestion.version}`}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <h3
                          className="font-semibold"
                          id={`suggestion-${suggestion.rule_id}`}
                        >
                          Generated suggestion
                        </h3>
                        <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-violet-900">
                          {suggestion.ai_generated
                            ? "AI-generated"
                            : "Policy-derived"}
                        </span>
                      </div>
                      {suggestion.suggested_language ? (
                        <blockquote className="mt-3 border-l-2 border-violet-300 pl-3 text-sm text-slate-800">
                          {suggestion.suggested_language}
                        </blockquote>
                      ) : null}
                      <p className="mt-3 text-sm text-slate-700">
                        {suggestion.review_recommendation}
                      </p>
                      {suggestion.comparison ? (
                        <p className="mt-2 text-sm text-slate-700">
                          {suggestion.comparison}
                        </p>
                      ) : null}
                    </section>
                  ))}

                  <nav aria-label="Finding citations" className="mt-5">
                    <ul className="flex flex-wrap gap-3 text-sm font-semibold">
                      {selectedFinding.citation_ids.map((citationId) => (
                        <li key={citationId}>
                          <a
                            className="underline"
                            href={`#source-${citationId}`}
                          >
                            View citation {citationId}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </nav>
                </article>
              ) : null}

              <section
                aria-labelledby="source-evidence-heading"
                className="rounded-2xl border border-slate-200 bg-white p-5"
                id="source-evidence"
                role="region"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2
                      className="text-xl font-semibold"
                      id="source-evidence-heading"
                    >
                      Source evidence
                    </h2>
                    <p className="mt-1 text-sm text-slate-600">
                      Cited text for the selected finding.
                    </p>
                  </div>
                  {documentUrl && selectedEvidence[0] ? (
                    <a
                      className="text-sm font-semibold underline"
                      href={`${documentUrl}#page=${selectedEvidence[0].pageNumber}`}
                    >
                      Open original document at page{" "}
                      {selectedEvidence[0].pageNumber}
                    </a>
                  ) : null}
                </div>
                {selectedEvidence.length ? (
                  <div className="mt-4 space-y-4">
                    {selectedEvidence.map((item) => (
                      <article
                        className="scroll-mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4"
                        id={`source-${item.citationId}`}
                        key={item.citationId}
                      >
                        <p className="text-sm font-semibold text-slate-700">
                          Page {item.pageNumber} · {label(item.kind)}
                        </p>
                        <mark className="mt-2 block bg-amber-200/70 text-slate-950">
                          {item.text}
                        </mark>
                        <a
                          className="mt-3 inline-block text-sm font-semibold underline"
                          href={`#source-${item.citationId}`}
                        >
                          Citation {item.citationId} on page {item.pageNumber}
                        </a>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-slate-600">
                    No source location is available for this finding.
                  </p>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
