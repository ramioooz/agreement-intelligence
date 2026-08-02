import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewWorkspace } from "@/components/review-workspace";

const lowConfidenceFinding = {
  id: "finding-confidentiality",
  rule_id: "rule-confidentiality",
  rule_title: "Confidentiality survival",
  clause_type: "confidentiality",
  reviewer_guidance: "Confirm the survival period.",
  result: "needs_review" as const,
  severity: "low",
  confidence: 0.62,
  method: "deterministic" as const,
  citation_ids: ["citation-confidentiality"],
  playbook_version_id: "playbook-version",
  extraction_version: "clause-rules.v1",
  review_state: "unreviewed",
  risk: {
    version: "playbook-risk.v1" as const,
    severity: "low",
    risk_rationale: "Confidentiality must survive termination.",
    risk_confidence: 0.62,
    review_status: "review_required",
    citation_ids: ["citation-confidentiality"],
    model_explanation: null,
  },
  fallback_suggestions: [],
};

const highRiskFinding = {
  id: "finding-liability",
  rule_id: "rule-liability",
  rule_title: "Prohibit unlimited liability",
  clause_type: "limitation_of_liability",
  reviewer_guidance: "Escalate uncapped liability for legal approval.",
  result: "non_compliant" as const,
  severity: "high",
  confidence: 0.94,
  method: "deterministic" as const,
  citation_ids: ["citation-liability"],
  playbook_version_id: "playbook-version",
  extraction_version: "clause-rules.v1",
  review_state: "unreviewed",
  risk: {
    version: "playbook-risk.v1" as const,
    severity: "high",
    risk_rationale: "Unlimited exposure conflicts with the approved cap.",
    risk_confidence: 0.94,
    review_status: "review_required",
    citation_ids: ["citation-liability"],
    model_explanation: "The clause does not state a monetary ceiling.",
  },
  fallback_suggestions: [],
};

describe("ReviewWorkspace", () => {
  it("synchronizes selected finding evidence and marks low-confidence findings for human review", () => {
    render(
      <ReviewWorkspace
        agreementId="agreement-1"
        agreementTitle="Supplier agreement"
        documentUrl="/api/documents/download?object_key=agreement.pdf"
        evidence={[
          {
            citationId: "citation-confidentiality",
            kind: "paragraph",
            pageNumber: 2,
            text: "Confidentiality obligations end on termination.",
          },
          {
            citationId: "citation-liability",
            kind: "paragraph",
            pageNumber: 7,
            text: "The supplier accepts unlimited liability.",
          },
        ]}
        findings={[lowConfidenceFinding, highRiskFinding]}
      />,
    );

    expect(
      within(
        screen.getByRole("button", {
          name: "Confidentiality — Confidentiality survival (rule rule-confidentiality), Low severity, Needs review, Human review required, Low confidence 62%",
        }),
      ).getByText("Human review required"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Source evidence" })).getByText(
        "The supplier accepts unlimited liability.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Confidentiality — Confidentiality survival (rule rule-confidentiality), Low severity, Needs review, Human review required, Low confidence 62%",
      }),
    );

    const evidencePanel = screen.getByRole("region", {
      name: "Source evidence",
    });
    expect(
      within(evidencePanel).getByText(
        "Confidentiality obligations end on termination.",
      ),
    ).toBeInTheDocument();
    expect(
      within(evidencePanel).queryByText(
        "The supplier accepts unlimited liability.",
      ),
    ).not.toBeInTheDocument();
    expect(
      within(evidencePanel).getByRole("link", {
        name: "Citation citation-confidentiality on page 2",
      }),
    ).toHaveAttribute("href", "#source-citation-confidentiality");
    expect(
      screen.getByRole("heading", { name: "Confidentiality survival" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Confidentiality · Low severity/),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("article", { name: "Confidentiality survival" }),
      ).getByText("Confirm the survival period."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Confidentiality — Confidentiality survival",
      }),
    ).toHaveAttribute("aria-current", "true");
  });

  it("sorts findings by legal severity before rendering or filtering", () => {
    const criticalFinding = {
      ...lowConfidenceFinding,
      id: "finding-critical",
      rule_id: "rule-critical",
      rule_title: "Stop work right",
      clause_type: "termination",
      severity: "critical",
      confidence: 0.9,
      result: "non_compliant" as const,
      citation_ids: [],
      risk: {
        ...lowConfidenceFinding.risk,
        severity: "critical",
        risk_confidence: 0.9,
      },
    };

    render(
      <ReviewWorkspace
        agreementId="agreement-1"
        agreementTitle="Supplier agreement"
        findings={[lowConfidenceFinding, highRiskFinding, criticalFinding]}
      />,
    );

    expect(
      screen
        .getAllByRole("button", { name: /severity/ })
        .map((button) => button.textContent),
    ).toEqual([
      expect.stringContaining("Critical severity"),
      expect.stringContaining("High severity"),
      expect.stringContaining("Low severity"),
    ]);
  });
});
