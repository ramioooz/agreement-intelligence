import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgreementRepository } from "@/components/agreement-repository";
import type { AgreementSummary } from "@/lib/agreement-api";

const agreement: AgreementSummary = {
  id: "55555555-5555-5555-5555-555555555555",
  organization_id: "11111111-1111-1111-1111-111111111111",
  workspace_id: "22222222-2222-2222-2222-222222222222",
  title: "Master services agreement",
  agreement_type: "services",
  status: "active",
  parties: [{ name: "Acme Bank", role: "customer" }],
  files: [
    {
      file_name: "msa.pdf",
      content_type: "application/pdf",
      storage_key: "tenant/document.pdf",
      checksum: "abc",
      byte_size: 1024,
      version_number: 1,
    },
  ],
  processing_state: "completed",
  audit_metadata: {},
  audit_events: [],
  archived_at: null,
  created_at: "2026-07-31T09:00:00Z",
  updated_at: "2026-07-31T09:00:00Z",
};

describe("AgreementRepository", () => {
  it("renders searchable, filterable agreement rows with pagination", () => {
    render(
      <AgreementRepository
        agreements={[agreement]}
        nextCursor="25"
        filters={{ query: "", status: "all", agreementType: "all" }}
      />,
    );

    expect(
      screen.getByRole("searchbox", { name: "Search agreements" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to dashboard" }),
    ).toHaveAttribute("href", "/dashboard");
    expect(screen.getByLabelText("Agreement status")).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Agreement repository" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Master services agreement" }),
    ).toHaveAttribute(
      "href",
      "/dashboard/agreements/55555555-5555-5555-5555-555555555555",
    );
    expect(screen.getByRole("link", { name: "Next page" })).toHaveAttribute(
      "href",
      expect.stringContaining("cursor=25"),
    );
  });

  it("announces loading, empty, and failure states", () => {
    const { rerender } = render(<AgreementRepository state="loading" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading agreements");

    rerender(
      <AgreementRepository
        agreements={[]}
        filters={{ query: "lease", status: "all", agreementType: "all" }}
      />,
    );
    expect(
      screen.getByText("No agreements match the current filters."),
    ).toBeInTheDocument();

    rerender(<AgreementRepository state="error" />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unable to load the agreement repository.",
    );
  });
});
