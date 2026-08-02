import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewDecisions } from "@/components/review-decisions";

describe("ReviewDecisions", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("records an accessible edited decision and announces reconstructed current state", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "decision-1",
          finding_id: "finding-1",
          action: "edited",
          original_result: "needs_review",
          rationale: "The exception requires a critical negotiated cap.",
          edited_result: "non_compliant",
          edited_severity: "critical",
          actor_id: "reviewer-1",
          occurred_at: "2026-08-02T10:00:00Z",
          current: {
            action: "edited",
            result: "non_compliant",
            severity: "critical",
            rationale: "The exception requires a critical negotiated cap.",
            actor_id: "reviewer-1",
            decided_at: "2026-08-02T10:00:00Z",
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    render(
      <ReviewDecisions
        currentDecision={null}
        decisionEvents={[]}
        findingId="finding-1"
        onRecorded={vi.fn()}
        originalResult="needs_review"
        originalSeverity="high"
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Edit finding" }));
    fireEvent.change(screen.getByLabelText("Edited result"), {
      target: { value: "non_compliant" },
    });
    fireEvent.change(screen.getByLabelText("Edited severity"), {
      target: { value: "critical" },
    });
    fireEvent.change(screen.getByLabelText("Reviewer rationale"), {
      target: {
        value: "The exception requires a critical negotiated cap.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    expect(
      await screen.findByRole("status", {
        name: "Current reviewer decision",
      }),
    ).toHaveTextContent("Edited · Non compliant · Critical severity");
    expect(
      screen.getByText("1 immutable decision event recorded."),
    ).toBeVisible();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(fetcher).toHaveBeenCalledWith(
      "/api/review-findings/finding-1/decisions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          action: "edited",
          rationale: "The exception requires a critical negotiated cap.",
          edited_result: "non_compliant",
          edited_severity: "critical",
        }),
      }),
    );
  });
});
