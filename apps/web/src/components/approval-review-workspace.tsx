"use client";

import Link from "next/link";
import { type FormEvent, useMemo, useState } from "react";

export type ApprovalReview = {
  id: string;
  agreement_id: string;
  agreement_version_id: string | null;
  state: string;
  created_by: string;
  revision: number;
  created_at: string;
};

export type ApprovalReviewComment = {
  id: string;
  review_id: string;
  finding_id: string | null;
  agreement_version_id: string | null;
  author_id: string;
  body: string;
  created_at: string;
};

export type FinalReviewPackage = {
  pdf_url: string;
  manifest_url: string;
  checksum: string;
  created_at: string;
};

type ApprovalReviewWorkspaceProps = {
  review: ApprovalReview;
  title: string;
  comments: ApprovalReviewComment[];
  canDecide: boolean;
  finalPackage?: FinalReviewPackage | null;
};

function label(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function dateTime(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function ApprovalReviewWorkspace({
  review,
  title,
  comments,
  canDecide,
  finalPackage,
}: ApprovalReviewWorkspaceProps) {
  const [commentBody, setCommentBody] = useState("");
  const [commentItems, setCommentItems] = useState(comments);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const timeline = useMemo(
    () => [
      {
        id: `created-${review.id}`,
        kind: "Review created",
        body: "The review was opened for this agreement version.",
        createdAt: review.created_at,
      },
      ...commentItems.map((comment) => ({
        id: comment.id,
        kind: comment.finding_id ? "Finding comment" : "Review comment",
        body: comment.body,
        createdAt: comment.created_at,
      })),
    ],
    [commentItems, review.created_at, review.id],
  );

  async function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = commentBody.trim();
    if (!body) return;
    setSubmitting(true);
    setError(undefined);
    try {
      const response = await fetch(`/api/reviews/${review.id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          body,
          agreement_version_id: review.agreement_version_id,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      if (!response.ok) throw new Error("review comment request failed");
      const recorded = (await response.json()) as ApprovalReviewComment;
      setCommentItems((current) => [...current, recorded]);
      setCommentBody("");
    } catch {
      setError("The comment could not be recorded. Check your access and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="approval-review-heading" className="space-y-6">
      <header>
        <Link
          className="text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-950 hover:underline"
          href="/dashboard/reviews"
        >
          Back to review inbox
        </Link>
        <p className="mt-5 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Approval review
        </p>
        <h1
          className="mt-2 text-3xl font-semibold tracking-tight"
          id="approval-review-heading"
        >
          {title}
        </h1>
        <p className="mt-2 text-slate-600">
          Agreement version {review.agreement_version_id ? "is pinned for this review." : "is not available."}
        </p>
      </header>

      <section
        aria-label="Review status"
        className="rounded-2xl border border-slate-200 bg-white p-5"
      >
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Review state
        </p>
        <p className="mt-2 text-xl font-semibold" role="status">
          {label(review.state)}
        </p>
        <p className="mt-2 text-sm text-slate-600">
          Revision {review.revision} · Opened {dateTime(review.created_at)}
        </p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <section
          aria-labelledby="review-timeline-heading"
          className="rounded-2xl border border-slate-200 bg-white p-5"
        >
          <h2 className="text-xl font-semibold" id="review-timeline-heading">
            Timeline
          </h2>
          <ol className="mt-5 space-y-4 border-l-2 border-slate-200 pl-5">
            {timeline.map((event) => (
              <li className="relative" key={event.id}>
                <span className="absolute -left-[1.7rem] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-slate-600" />
                <p className="font-semibold">{event.kind}</p>
                <p className="mt-1 text-sm text-slate-700">{event.body}</p>
                <time className="mt-1 block text-xs text-slate-500">
                  {dateTime(event.createdAt)}
                </time>
              </li>
            ))}
          </ol>
        </section>

        <aside className="space-y-6">
          <section
            aria-labelledby="approval-action-heading"
            className="rounded-2xl border border-slate-200 bg-white p-5"
          >
            <h2 className="text-xl font-semibold" id="approval-action-heading">
              Approval action
            </h2>
            {canDecide ? (
              <p className="mt-2 text-sm text-slate-600">
                Approval actions become available when the workflow activates your stage.
              </p>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                You can view this review, but are not eligible to record an approval decision.
              </p>
            )}
          </section>

          <section
            aria-labelledby="final-package-heading"
            className="rounded-2xl border border-slate-200 bg-white p-5"
          >
            <h2 className="text-xl font-semibold" id="final-package-heading">
              Final package
            </h2>
            {finalPackage ? (
              <>
                <p className="mt-2 text-sm text-slate-600">
                  Generated {dateTime(finalPackage.created_at)} · {finalPackage.checksum}
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  <a className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white" href={finalPackage.pdf_url}>
                    Download final PDF
                  </a>
                  <a className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold" href={finalPackage.manifest_url}>
                    Download JSON manifest
                  </a>
                </div>
              </>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                Final package will be available when the approval workflow completes.
              </p>
            )}
          </section>
        </aside>
      </div>

      <section
        aria-labelledby="review-comment-heading"
        className="rounded-2xl border border-slate-200 bg-white p-5"
      >
        <h2 className="text-xl font-semibold" id="review-comment-heading">
          Add a comment
        </h2>
        {canDecide ? (
          <form className="mt-4 space-y-3" onSubmit={submitComment}>
            <label className="grid gap-1.5 text-sm font-medium">
              Review comment
              <textarea
                className="min-h-28 rounded-lg border border-slate-300 px-3 py-2"
                maxLength={4000}
                onChange={(event) => setCommentBody(event.target.value)}
                required
                value={commentBody}
              />
            </label>
            {error ? <p className="text-sm font-medium text-rose-800" role="alert">{error}</p> : null}
            <button
              className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              disabled={submitting || !commentBody.trim()}
              type="submit"
            >
              {submitting ? "Adding comment…" : "Add comment"}
            </button>
          </form>
        ) : (
          <p className="mt-2 text-sm text-slate-600">
            You do not have permission to add comments to this review.
          </p>
        )}
      </section>
    </section>
  );
}
