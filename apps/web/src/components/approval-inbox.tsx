import Link from "next/link";

export type ReviewAssignment = {
  id: string;
  review_id: string;
  assignee_id: string;
  assigned_by: string;
  predecessor_assignment_id: string | null;
  due_at: string | null;
  status: string;
  created_at: string;
};

type ApprovalInboxProps = {
  assignments: ReviewAssignment[];
  unreadCount: number;
};

function dueLabel(value: string | null): string {
  if (!value) return "No deadline";
  return `Due ${new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value))}`;
}

export function ApprovalInbox({
  assignments,
  unreadCount,
}: ApprovalInboxProps) {
  return (
    <section aria-labelledby="review-inbox-heading" className="space-y-6">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">
          Approval workflow
        </p>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1
              className="text-3xl font-semibold tracking-tight"
              id="review-inbox-heading"
            >
              Review inbox
            </h1>
            <p className="mt-2 text-slate-600">
              Role-aware assignments, deadlines, and decisions for your
              workspace.
            </p>
          </div>
          <span
            className="rounded-full bg-indigo-50 px-3 py-1.5 text-sm font-semibold text-indigo-800"
            role="status"
          >
            {unreadCount} unread notification{unreadCount === 1 ? "" : "s"}
          </span>
        </div>
      </header>

      {assignments.length ? (
        <div
          className="grid gap-4"
          role="list"
          aria-label="Active review assignments"
        >
          {assignments.map((assignment) => (
            <article
              className="rounded-2xl border border-slate-200 bg-white p-5"
              key={assignment.id}
              role="listitem"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Active assignment
                  </p>
                  <h2 className="mt-2 text-xl font-semibold">
                    Review {assignment.review_id}
                  </h2>
                  <p className="mt-2 text-sm text-slate-600">
                    Status:{" "}
                    <span className="font-semibold">{assignment.status}</span> ·{" "}
                    {dueLabel(assignment.due_at)}
                  </p>
                </div>
                <Link
                  className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white"
                  href={`/dashboard/reviews/${assignment.review_id}`}
                >
                  Open review {assignment.review_id}
                </Link>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center">
          <h2 className="text-xl font-semibold">
            No active review assignments
          </h2>
          <p className="mt-2 text-slate-600">
            New assignments and escalation events will appear here.
          </p>
          <Link
            className="mt-5 inline-flex rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold"
            href="/dashboard/agreements"
          >
            Browse agreements
          </Link>
        </div>
      )}
    </section>
  );
}
