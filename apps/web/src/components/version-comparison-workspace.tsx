"use client";

import { useMemo, useState } from "react";
import type { AgreementVersion } from "@/lib/agreement-api";
import type { DocumentAnalysis } from "@/lib/agreement-api";
import type { VersionComparison } from "@/lib/version-comparison-api";

type Props = {
  versions: AgreementVersion[];
  comparison?: VersionComparison;
  baselineAnalysis?: DocumentAnalysis;
  targetAnalysis?: DocumentAnalysis;
  compareAction?: (formData: FormData) => void | Promise<void>;
};

const severityOrder = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  none: 4,
} as const;

function blocks(analysis: DocumentAnalysis | undefined) {
  return (
    analysis?.document.pages.flatMap((page) =>
      page.blocks.map((block) => ({ ...block, page: page.number })),
    ) ?? []
  );
}

function versionLabel(version: AgreementVersion) {
  return `Version ${version.version_number} · ${version.file.file_name}`;
}

export function VersionComparisonWorkspace({
  versions,
  comparison,
  baselineAnalysis,
  targetAnalysis,
  compareAction,
}: Props) {
  const completed = versions.filter(
    (version) => version.processing_state === "completed",
  );
  const sorted = [...completed].sort(
    (left, right) => left.version_number - right.version_number,
  );
  const [baseline, setBaseline] = useState(sorted.at(-2)?.id ?? "");
  const [target, setTarget] = useState(sorted.at(-1)?.id ?? "");
  const [severity, setSeverity] = useState("all");
  const [kind, setKind] = useState("all");
  const [reviewOnly, setReviewOnly] = useState(false);
  const visibleChanges = useMemo(
    () =>
      (comparison?.changes ?? []).filter(
        (change) =>
          (severity === "all" || change.severity === severity) &&
          (kind === "all" || change.alignment_kind === kind) &&
          (!reviewOnly || change.review_required),
      ),
    [comparison, severity, kind, reviewOnly],
  );
  const leftBlocks = blocks(baselineAnalysis);
  const rightBlocks = blocks(targetAnalysis);

  return (
    <section className="space-y-6" aria-label="Version comparison workspace">
      <header>
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Version intelligence
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          Compare agreement versions
        </h1>
        <p className="mt-2 text-slate-600">
          Review aligned clauses, deterministic word changes, and cited
          evidence.
        </p>
      </header>
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
          <label className="grid gap-1 text-sm font-medium">
            Baseline version
            <select
              aria-label="Baseline version"
              className="rounded-lg border border-slate-300 px-3 py-2"
              value={baseline}
              onChange={(event) => setBaseline(event.target.value)}
            >
              {sorted.map((version) => (
                <option key={version.id} value={version.id}>
                  {versionLabel(version)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Target version
            <select
              aria-label="Target version"
              className="rounded-lg border border-slate-300 px-3 py-2"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              {sorted.map((version) => (
                <option key={version.id} value={version.id}>
                  {versionLabel(version)}
                </option>
              ))}
            </select>
          </label>
          {compareAction ? (
            <form action={compareAction}>
              <input
                name="baseline_version_id"
                type="hidden"
                value={baseline}
              />
              <input name="target_version_id" type="hidden" value={target} />
              <button
                className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
                type="submit"
                disabled={!baseline || !target || baseline === target}
              >
                Compare versions
              </button>
            </form>
          ) : null}
        </div>
        {completed.length < 2 ? (
          <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            Two completed versions are required before comparison can start.
          </p>
        ) : null}
        {comparison?.state === "queued" ||
        comparison?.state === "processing" ? (
          <p
            className="mt-4 rounded-lg bg-sky-50 p-3 text-sm text-sky-900"
            role="status"
          >
            Comparison is {comparison.state}. This page will show changes when
            processing completes.
          </p>
        ) : null}
        {comparison?.state === "failed" ? (
          <p
            className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-900"
            role="alert"
          >
            Comparison failed
            {comparison.failure_message
              ? `: ${comparison.failure_message}`
              : "."}
          </p>
        ) : null}
      </section>
      {comparison?.state === "completed" ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-end gap-4">
              <label className="grid gap-1 text-sm font-medium">
                Severity
                <select
                  aria-label="Filter by severity"
                  className="rounded-lg border border-slate-300 px-3 py-2"
                  value={severity}
                  onChange={(event) => setSeverity(event.target.value)}
                >
                  <option value="all">All severities</option>
                  {Object.keys(severityOrder)
                    .filter((value) => value !== "none")
                    .map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                </select>
              </label>
              <label className="grid gap-1 text-sm font-medium">
                Change type
                <select
                  aria-label="Filter by change type"
                  className="rounded-lg border border-slate-300 px-3 py-2"
                  value={kind}
                  onChange={(event) => setKind(event.target.value)}
                >
                  <option value="all">All change types</option>
                  {[
                    "matched",
                    "moved",
                    "split",
                    "merged",
                    "added",
                    "removed",
                  ].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 pb-2 text-sm font-medium">
                <input
                  aria-label="Review required only"
                  type="checkbox"
                  checked={reviewOnly}
                  onChange={(event) => setReviewOnly(event.target.checked)}
                />{" "}
                Review required only
              </label>
            </div>
          </section>
          <section className="grid gap-6 lg:grid-cols-2">
            <StructuredPane title="Baseline" blocks={leftBlocks} />
            <StructuredPane title="Target" blocks={rightBlocks} />
          </section>
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <h2 className="text-xl font-semibold">Material changes</h2>
            {visibleChanges.length === 0 ? (
              <p className="mt-3 text-sm text-slate-600">
                No changes match the selected filters.
              </p>
            ) : (
              <ol className="mt-4 space-y-4">
                {visibleChanges.map((change) => (
                  <li
                    className="rounded-xl border border-slate-200 p-4"
                    key={change.id}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold uppercase">
                        {change.alignment_kind}
                      </span>
                      <span
                        className={`rounded-full px-2 py-1 text-xs font-semibold ${change.severity === "critical" || change.severity === "high" ? "bg-rose-100 text-rose-900" : "bg-amber-100 text-amber-900"}`}
                      >
                        {change.severity} severity
                      </span>
                      {change.review_required ? (
                        <span className="rounded-full bg-violet-100 px-2 py-1 text-xs font-semibold text-violet-900">
                          Review required
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-2 text-sm text-slate-700">
                      {change.rationale}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-3 text-sm">
                      {change.baseline_citation_ids.map((id) => (
                        <a
                          className="font-semibold underline"
                          href={`/dashboard/agreements/${comparison.agreement_id}?citation=${encodeURIComponent(id)}&version=${comparison.baseline_version_id}`}
                          key={`b-${id}`}
                        >
                          View baseline citation
                        </a>
                      ))}
                      {change.target_citation_ids.map((id) => (
                        <a
                          className="font-semibold underline"
                          href={`/dashboard/agreements/${comparison.agreement_id}?citation=${encodeURIComponent(id)}&version=${comparison.target_version_id}`}
                          key={`t-${id}`}
                        >
                          View target citation
                        </a>
                      ))}
                    </div>
                    <p className="mt-3 font-mono text-sm">
                      {change.word_diff.map((part, index) => (
                        <span
                          className={
                            part.operation === "insert"
                              ? "bg-emerald-100"
                              : part.operation === "delete"
                                ? "bg-rose-100 line-through"
                                : ""
                          }
                          key={`${change.id}-${index}`}
                        >
                          {part.text}
                        </span>
                      ))}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}

function StructuredPane({
  title,
  blocks,
}: {
  title: string;
  blocks: Array<{ anchor_id: string; text: string; page: number }>;
}) {
  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-5"
      aria-label={`${title} structured text`}
    >
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="mt-4 max-h-[620px] space-y-3 overflow-auto">
        {blocks.length ? (
          blocks.map((block) => (
            <article
              className="rounded-lg border border-slate-100 p-3"
              id={`comparison-${title.toLowerCase()}-${block.anchor_id}`}
              key={block.anchor_id}
            >
              <p className="text-xs font-semibold uppercase text-slate-500">
                Page {block.page}
              </p>
              <p className="mt-1 text-sm text-slate-700">{block.text}</p>
            </article>
          ))
        ) : (
          <p className="text-sm text-slate-600">
            Structured text is not available for this version yet.
          </p>
        )}
      </div>
    </section>
  );
}
