"use client";

import { type FormEvent, useState } from "react";

import type {
  CurrentReviewDecision,
  FindingResult,
  ReviewDecisionAction,
  ReviewDecisionEvent,
} from "@/lib/review-api";

type ReviewDecisionsProps = {
  findingId: string;
  originalResult: FindingResult;
  originalSeverity: string;
  decisionEvents: ReviewDecisionEvent[];
  currentDecision: CurrentReviewDecision | null;
  onRecorded: (
    decision: ReviewDecisionEvent,
    current: CurrentReviewDecision,
  ) => void;
};

type ReviewDecisionResponse = ReviewDecisionEvent & {
  current: CurrentReviewDecision;
};

function label(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

export function ReviewDecisions({
  findingId,
  originalResult,
  originalSeverity,
  decisionEvents,
  currentDecision,
  onRecorded,
}: ReviewDecisionsProps) {
  const [action, setAction] = useState<ReviewDecisionAction>("accepted");
  const [editedResult, setEditedResult] =
    useState<FindingResult>(originalResult);
  const [editedSeverity, setEditedSeverity] = useState(originalSeverity);
  const [rationale, setRationale] = useState("");
  const [events, setEvents] = useState(decisionEvents);
  const [current, setCurrent] = useState(currentDecision);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>();

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    const body = {
      action,
      rationale,
      ...(action === "edited"
        ? { edited_result: editedResult, edited_severity: editedSeverity }
        : {}),
    };
    try {
      const response = await fetch(
        `/api/review-findings/${findingId}/decisions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!response.ok) throw new Error("decision request failed");
      const recorded = (await response.json()) as ReviewDecisionResponse;
      const { current: reconstructed, ...decision } = recorded;
      setEvents((existing) => [...existing, decision]);
      setCurrent(reconstructed);
      onRecorded(decision, reconstructed);
      setRationale("");
    } catch {
      setError("The reviewer decision could not be recorded. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      aria-labelledby={`review-decision-${findingId}`}
      className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4"
    >
      <h3 className="font-semibold" id={`review-decision-${findingId}`}>
        Reviewer decision
      </h3>
      {current ? (
        <p
          aria-label="Current reviewer decision"
          className="mt-2 text-sm font-semibold text-emerald-950"
          role="status"
        >
          {label(current.action)} · {label(current.result)} ·{" "}
          {label(current.severity)} severity
        </p>
      ) : (
        <p className="mt-2 text-sm text-slate-700">
          No reviewer decision has been recorded.
        </p>
      )}
      <p className="mt-1 text-sm text-slate-600">
        {events.length} immutable decision{" "}
        {events.length === 1 ? "event" : "events"} recorded.
      </p>

      <form className="mt-4 space-y-4" onSubmit={submitDecision}>
        <fieldset>
          <legend className="text-sm font-semibold">Decision action</legend>
          <div className="mt-2 flex flex-wrap gap-4 text-sm">
            {(
              [
                ["accepted", "Accept finding"],
                ["rejected", "Reject finding"],
                ["edited", "Edit finding"],
              ] as const
            ).map(([value, text]) => (
              <label className="flex items-center gap-2" key={value}>
                <input
                  checked={action === value}
                  name={`decision-action-${findingId}`}
                  onChange={() => setAction(value)}
                  type="radio"
                  value={value}
                />
                {text}
              </label>
            ))}
          </div>
        </fieldset>

        {action === "edited" ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-sm font-medium">
              Edited result
              <select
                className="rounded-lg border border-slate-300 bg-white px-3 py-2"
                onChange={(event) =>
                  setEditedResult(event.target.value as FindingResult)
                }
                value={editedResult}
              >
                <option value="satisfied">Satisfied</option>
                <option value="missing">Missing</option>
                <option value="non_compliant">Non compliant</option>
                <option value="needs_review">Needs review</option>
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Edited severity
              <select
                className="rounded-lg border border-slate-300 bg-white px-3 py-2"
                onChange={(event) => setEditedSeverity(event.target.value)}
                value={editedSeverity}
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
          </div>
        ) : null}

        <label className="grid gap-1 text-sm font-medium">
          Reviewer rationale
          <textarea
            className="min-h-24 rounded-lg border border-slate-300 bg-white px-3 py-2"
            maxLength={4000}
            onChange={(event) => setRationale(event.target.value)}
            required
            value={rationale}
          />
        </label>
        {error ? (
          <p className="text-sm font-medium text-rose-800" role="alert">
            {error}
          </p>
        ) : null}
        <button
          className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={submitting}
          type="submit"
        >
          {submitting ? "Recording decision…" : "Record decision"}
        </button>
      </form>
    </section>
  );
}
