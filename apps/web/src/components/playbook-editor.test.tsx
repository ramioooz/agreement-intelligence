import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlaybookEditor } from "@/components/playbook-editor";
import type { PlaybookVersion } from "@/lib/playbook-api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

const draft: PlaybookVersion = {
  id: "44444444-4444-4444-4444-444444444444",
  playbook_id: "33333333-3333-3333-3333-333333333333",
  organization_id: "11111111-1111-1111-1111-111111111111",
  workspace_id: "22222222-2222-2222-2222-222222222222",
  name: "Client Agreement",
  version: 1,
  status: "draft",
  agreement_family: "client_agreement",
  rules: [],
  audit_events: [],
  created_at: "2026-08-01T09:00:00Z",
  published_at: null,
};

const published: PlaybookVersion = {
  ...draft,
  status: "published",
  published_at: "2026-08-01T10:00:00Z",
  rules: [
    {
      id: "55555555-5555-5555-5555-555555555555",
      clause_type: "limitation_of_liability",
      title: "Limitation of liability",
      policy_type: "required",
      preferred_language: "Liability is capped at the fees paid.",
      fallback_language: "Liability is capped at twice the fees paid.",
      severity: "high",
      legal_rationale: "Keeps liability within approved risk tolerance.",
      reviewer_guidance: "Escalate uncapped liability.",
      evaluation_config: {
        method: "semantic",
        semantic_assessment_permitted: true,
      },
    },
  ],
};

describe("PlaybookEditor", () => {
  it("shows platform-admin draft controls and keeps publication disabled without a complete rule", () => {
    render(<PlaybookEditor canManage playbook={draft} />);

    expect(
      screen.getByRole("heading", { name: "Add rule" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Clause type")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Publish version" }),
    ).toBeDisabled();
  });

  it("hides mutation controls from users without the management capability", () => {
    render(<PlaybookEditor canManage={false} playbook={draft} />);

    expect(
      screen.queryByRole("heading", { name: "Add rule" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Publish version" }),
    ).not.toBeInTheDocument();
  });

  it("renders every authoritative published policy field read-only", () => {
    render(<PlaybookEditor canManage playbook={published} />);

    expect(
      screen.getByText("Liability is capped at the fees paid."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Liability is capped at twice the fees paid."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Keeps liability within approved risk tolerance."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Escalate uncapped liability."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Semantic assessment.*Permitted/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save rule" }),
    ).not.toBeInTheDocument();
  });
});
