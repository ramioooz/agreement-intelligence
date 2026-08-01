import type { PlaybookFindingResponse } from "@/lib/review-api";

type ReviewFindingListProps = {
  findings: PlaybookFindingResponse[];
  selectedFindingId?: string;
  onSelect: (findingId: string) => void;
};

export function findingResultLabel(
  result: PlaybookFindingResponse["result"],
): string {
  return result
    .replaceAll("_", " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

function label(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

function severityClasses(severity: string): string {
  if (severity === "critical" || severity === "high") {
    return "bg-rose-100 text-rose-900";
  }
  if (severity === "medium") return "bg-amber-100 text-amber-900";
  return "bg-slate-100 text-slate-700";
}

export function ReviewFindingList({
  findings,
  selectedFindingId,
  onSelect,
}: ReviewFindingListProps) {
  return (
    <ul className="mt-4 space-y-3">
      {findings.map((finding) => {
        const severity = `${finding.severity[0]?.toUpperCase() ?? ""}${finding.severity.slice(1)}`;
        const result = findingResultLabel(finding.result);
        const humanReviewRequired =
          finding.confidence < 0.8 ||
          finding.result === "needs_review" ||
          finding.risk.review_status === "review_required";
        const lowConfidence = finding.confidence < 0.8;
        const accessibleName = [
          `${label(finding.clause_type)} — ${finding.rule_title} (rule ${finding.rule_id})`,
          `${severity} severity`,
          result,
          humanReviewRequired ? "Human review required" : null,
          lowConfidence
            ? `Low confidence ${Math.round(finding.confidence * 100)}%`
            : null,
        ]
          .filter(Boolean)
          .join(", ");

        return (
          <li key={finding.id}>
            <button
              aria-label={accessibleName}
              aria-pressed={selectedFindingId === finding.id}
              className="w-full rounded-xl border border-slate-200 bg-white p-4 text-left hover:border-slate-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-950 aria-pressed:border-slate-950 aria-pressed:ring-1 aria-pressed:ring-slate-950"
              onClick={() => onSelect(finding.id)}
              type="button"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2 py-1 text-xs font-semibold ${severityClasses(finding.severity)}`}
                >
                  {severity} severity
                </span>
                <span className="font-semibold">{result}</span>
              </span>
              <span className="mt-2 block text-sm text-slate-600">
                <span className="block font-semibold text-slate-900">
                  {label(finding.clause_type)} · {finding.rule_title}
                </span>
                <span className="mt-1 block">
                  {finding.reviewer_guidance ||
                    "No reviewer guidance is recorded for this rule."}
                </span>
                Confidence {Math.round(finding.confidence * 100)}% ·{" "}
                {finding.method === "deterministic"
                  ? "Deterministic evaluation"
                  : "Semantic evaluation"}
              </span>
              {humanReviewRequired ? (
                <span className="mt-2 block text-sm font-semibold text-amber-900">
                  Human review required
                </span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
