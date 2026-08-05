import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApprovalInbox } from "@/components/approval-inbox";

describe("ApprovalInbox", () => {
  it("lists assigned reviews with status and links to the review workspace", () => {
    render(
      <ApprovalInbox
        assignments={[
          {
            id: "assignment-1",
            review_id: "review-1",
            assignee_id: "user-1",
            assigned_by: "admin-1",
            predecessor_assignment_id: null,
            due_at: "2026-08-06T10:00:00Z",
            status: "active",
            created_at: "2026-08-05T10:00:00Z",
          },
        ]}
        unreadCount={2}
      />,
    );

    expect(screen.getByRole("heading", { name: "Review inbox" })).toBeVisible();
    expect(screen.getByText("2 unread notifications")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open review review-1" })).toHaveAttribute(
      "href",
      "/dashboard/reviews/review-1",
    );
    expect(screen.getByRole("listitem")).toHaveTextContent("Due Aug 6, 2026");
  });

  it("renders an actionable empty state", () => {
    render(<ApprovalInbox assignments={[]} unreadCount={0} />);
    expect(screen.getByText("No active review assignments")).toBeVisible();
    expect(screen.getByRole("link", { name: "Browse agreements" })).toHaveAttribute(
      "href",
      "/dashboard/agreements",
    );
  });
});
