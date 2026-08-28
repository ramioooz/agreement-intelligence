import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApprovalReviewWorkspace } from "@/components/approval-review-workspace";
import { getFinalReviewPackage } from "@/lib/approval-api";

const review = {
  id: "review-1",
  agreement_id: "agreement-1",
  agreement_version_id: "version-2",
  state: "awaiting_approval",
  created_by: "requester-1",
  revision: 3,
  created_at: "2026-08-05T10:00:00Z",
};

describe("ApprovalReviewWorkspace", () => {
  it("shows an assigned reviewer the timeline, comment action, and pending package state", () => {
    render(
      <ApprovalReviewWorkspace
        canDecide
        comments={[
          {
            id: "comment-1",
            review_id: review.id,
            finding_id: null,
            agreement_version_id: "version-2",
            author_id: "reviewer-1",
            body: "The liability cap needs legal review.",
            created_at: "2026-08-05T11:00:00Z",
          },
        ]}
        review={review}
        title="Master services agreement"
      />,
    );

    expect(screen.getByText("Approval review")).toBeVisible();
    expect(screen.getByText(/Awaiting approval/i)).toBeVisible();
    expect(
      screen.getByText("The liability cap needs legal review."),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Final package will be available when the approval workflow completes.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Add comment" })).toBeDisabled();
  });

  it("adds a comment without losing the existing immutable timeline", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            id: "comment-2",
            review_id: review.id,
            finding_id: null,
            agreement_version_id: "version-2",
            author_id: "reviewer-1",
            body: "Escalated to the business approver.",
            created_at: "2026-08-05T12:00:00Z",
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(
      <ApprovalReviewWorkspace
        canDecide
        comments={[]}
        review={review}
        title="Master services agreement"
      />,
    );

    fireEvent.change(screen.getByLabelText("Review comment"), {
      target: { value: "Escalated to the business approver." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add comment" }));

    expect(
      await screen.findByText("Escalated to the business approver."),
    ).toBeVisible();
    expect(screen.getByText("Review created")).toBeVisible();
  });

  it("exposes immutable package downloads only after workflow completion", () => {
    render(
      <ApprovalReviewWorkspace
        canDecide={false}
        comments={[]}
        finalPackage={{
          manifest_url: "/reviews/review-1/final-package/manifest",
          pdf_url: "/reviews/review-1/final-package/pdf",
          checksum: "sha256:package",
          manifest_checksum: "sha256:manifest",
          pdf_checksum: "sha256:pdf",
          created_at: "2026-08-05T13:00:00Z",
        }}
        review={{ ...review, state: "approved" }}
        title="Master services agreement"
      />,
    );

    expect(
      screen.getByRole("link", { name: "Download final PDF" }),
    ).toHaveAttribute("href", "/api/reviews/review-1/final-package/pdf");
    expect(
      screen.getByRole("link", { name: "Download JSON manifest" }),
    ).toHaveAttribute("href", "/api/reviews/review-1/final-package/manifest");
    expect(screen.getByText("Manifest sha256:manifest")).toBeVisible();
    expect(screen.getByText("PDF sha256:pdf")).toBeVisible();
  });

  it("keeps package downloads hidden while an approved package is pending", () => {
    render(
      <ApprovalReviewWorkspace
        canDecide={false}
        comments={[]}
        finalPackage={null}
        review={{ ...review, state: "approved" }}
        title="Master services agreement"
        workflow={{
          id: "workflow-1",
          state: "approved",
          active_stage_ordinal: null,
          revision: 4,
        }}
      />,
    );

    expect(screen.getByText(/final package is being prepared/i)).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "Download final PDF" }),
    ).not.toBeInTheDocument();
  });

  it("treats the durable worker package delay as a retryable pending state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: "final_package_pending", retryable: true },
          }),
          { status: 503, headers: { "Retry-After": "3" } },
        ),
      ),
    );

    await expect(
      getFinalReviewPackage({
        baseUrl: "https://api.example.test",
        scope: { organizationId: "org", workspaceId: "workspace" },
        reviewId: review.id,
      }),
    ).resolves.toBeNull();
  });

  it("records an approval against the workflow revision", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            id: "workflow-1",
            state: "approved",
            active_stage_ordinal: null,
            revision: 4,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    render(
      <ApprovalReviewWorkspace
        canDecide
        comments={[]}
        review={review}
        title="Master services agreement"
        workflow={{
          id: "workflow-1",
          state: "waiting_for_approval",
          active_stage_ordinal: 1,
          revision: 3,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(
      await screen.findByText(/Approval actions become available/i),
    ).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      "/api/reviews/review-1/workflow/decisions",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
