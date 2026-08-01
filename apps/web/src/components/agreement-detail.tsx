import Link from "next/link";

import type { AgreementSummary } from "@/lib/agreement-api";
import type { DocumentAnalysis } from "@/lib/agreement-api";
import type { ProcessingJob } from "@/lib/processing-api";

type AgreementDetailProps = {
  agreement: AgreementSummary;
  documentUrl?: string;
  processingJob?: ProcessingJob;
  retryAction?: () => void | Promise<void>;
  startAnalysisAction?: () => void | Promise<void>;
  analysis?: DocumentAnalysis;
};

function date(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "Not recorded";
}

export function AgreementDetail({
  agreement,
  documentUrl,
  processingJob,
  retryAction,
  startAnalysisAction,
  analysis,
}: AgreementDetailProps) {
  const file = agreement.files[0];
  const isPdf = file?.content_type === "application/pdf";
  const timeline = [
    ["Created", agreement.created_at],
    ["Queued", processingJob?.queued_at],
    ["Processing started", processingJob?.processing_started_at],
    [
      processingJob?.state === "failed" ? "Failed" : "Completed",
      processingJob?.failed_at ?? processingJob?.completed_at,
    ],
  ].filter((event): event is [string, string] => Boolean(event[1]));

  return (
    <section className="space-y-8">
      <Link
        className="text-sm font-semibold underline-offset-4 hover:underline"
        href="/dashboard/agreements"
      >
        Back to repository
      </Link>
      <header>
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {agreement.agreement_type}
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
          {agreement.title}
        </h1>
        <p className="mt-2 text-slate-600">
          Status: {agreement.status} · Processing: {agreement.processing_state}
        </p>
      </header>
      <div className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
        <section
          aria-labelledby="document-heading"
          className="rounded-2xl border border-slate-200 bg-white p-5"
        >
          <h2 className="text-xl font-semibold" id="document-heading">
            Original document
          </h2>
          {file && documentUrl ? (
            isPdf ? (
              <iframe
                className="mt-4 h-[620px] w-full rounded-lg border border-slate-200"
                src={documentUrl}
                title="PDF document viewer"
              />
            ) : (
              <div className="mt-4 rounded-lg bg-slate-50 p-5">
                <p className="font-medium">
                  DOCX files are provided as an original download to preserve
                  their contents safely.
                </p>
                <Link
                  className="mt-3 inline-block rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"
                  download
                  href={documentUrl}
                >
                  Download original DOCX
                </Link>
              </div>
            )
          ) : (
            <p className="mt-4 text-slate-600">
              No original document is attached.
            </p>
          )}
        </section>
        <aside className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <h2 className="text-xl font-semibold">Metadata</h2>
            <dl className="mt-4 grid gap-3 text-sm">
              <div>
                <dt className="text-slate-500">Parties</dt>
                <dd>
                  {agreement.parties
                    .map((party) => `${party.name} (${party.role})`)
                    .join(", ") || "Not recorded"}
                </dd>
              </div>
              <div>
                <dt className="text-slate-500">File</dt>
                <dd>{file?.file_name ?? "Not recorded"}</dd>
              </div>
              <div>
                <dt className="text-slate-500">Last updated</dt>
                <dd>{date(agreement.updated_at)}</dd>
              </div>
            </dl>
          </section>
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <h2 className="text-xl font-semibold">Processing</h2>
            <ol
              aria-label="Processing timeline"
              className="mt-4 space-y-3 border-l-2 border-slate-200 pl-4"
            >
              {timeline.map(([label, occurredAt]) => (
                <li key={label}>
                  <p className="font-medium">{label}</p>
                  <p className="text-sm text-slate-500">{date(occurredAt)}</p>
                </li>
              ))}
            </ol>
            {processingJob?.failure_message ? (
              <p className="mt-4 text-sm text-rose-800">
                {processingJob.failure_message}
              </p>
            ) : null}
            {processingJob?.retry_permitted ? (
              <form action={retryAction} className="mt-4">
                <button
                  className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
                  type="submit"
                >
                  Retry processing
                </button>
              </form>
            ) : null}
            {startAnalysisAction ? (
              <form action={startAnalysisAction} className="mt-4">
                <button
                  className="rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
                  type="submit"
                >
                  Start analysis
                </button>
              </form>
            ) : null}
          </section>
        </aside>
      </div>
      {analysis ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="text-xl font-semibold">Document understanding</h2>
          {analysis.classification ? (
            <section className="mt-4 rounded-lg bg-slate-50 p-4">
              <h3 className="font-semibold">Agreement family</h3>
              <p className="mt-1 capitalize">
                {analysis.classification.family.replaceAll("_", " ")}
              </p>
              <p className="mt-1 text-sm text-slate-600">
                {analysis.classification.rationale} · Confidence{" "}
                {analysis.classification.confidence}
              </p>
            </section>
          ) : null}
          {analysis.clauses.length ? (
            <section className="mt-5">
              <h3 className="font-semibold">Extracted clauses</h3>
              <ul className="mt-3 space-y-3">
                {analysis.clauses.map((clause) => (
                  <li
                    className="rounded-lg border border-slate-200 p-3"
                    key={clause.category}
                  >
                    <p className="font-medium capitalize">
                      {clause.category.replaceAll("_", " ")}
                    </p>
                    <p className="mt-1 text-sm text-slate-700">
                      {clause.source_text}
                    </p>
                    <a
                      className="mt-2 inline-block text-sm font-semibold underline"
                      href={`#evidence-${clause.citation_anchor_ids[0]}`}
                    >
                      View source evidence
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {Object.entries(analysis.summaries).map(([audience, summary]) => (
            <section className="mt-5" key={audience}>
              <h3 className="font-semibold capitalize">{audience} summary</h3>
              {summary.claims.map((claim) => (
                <a
                  className="mt-2 block text-sm text-slate-700 underline"
                  href={`#evidence-${claim.citation_anchor_ids[0]}`}
                  key={claim.citation_anchor_ids[0]}
                >
                  {claim.text}
                </a>
              ))}
            </section>
          ))}
          {analysis.diagnostics.map((diagnostic) => (
            <p
              className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
              key={diagnostic.code}
            >
              {diagnostic.code === "ocr_required"
                ? "OCR is required before these scanned pages can be reviewed."
                : diagnostic.message}
            </p>
          ))}
          {analysis.document.pages.map((page) => (
            <section className="mt-5" key={page.number}>
              <h3 className="font-semibold">Extracted page {page.number}</h3>
              {page.blocks.map((block) => (
                <p
                  className="mt-2 text-sm text-slate-700"
                  id={`evidence-${block.anchor_id}`}
                  key={block.anchor_id}
                >
                  {block.text}
                </p>
              ))}
            </section>
          ))}
        </section>
      ) : null}
    </section>
  );
}
