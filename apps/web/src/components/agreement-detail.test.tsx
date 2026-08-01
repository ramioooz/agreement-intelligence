import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgreementDetail } from "@/components/agreement-detail";
import type { AgreementSummary, DocumentAnalysis } from "@/lib/agreement-api";
import type { ProcessingJob } from "@/lib/processing-api";

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
      file_name: "msa.docx",
      content_type:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      storage_key: "tenant/document.docx",
      checksum: "abc",
      byte_size: 1024,
      version_number: 1,
    },
  ],
  processing_state: "failed",
  audit_metadata: { source: "upload" },
  audit_events: [
    {
      action: "created",
      actor_id: "user-1",
      occurred_at: "2026-07-31T09:00:00Z",
    },
  ],
  archived_at: null,
  created_at: "2026-07-31T09:00:00Z",
  updated_at: "2026-07-31T10:00:00Z",
};

const job: ProcessingJob = {
  id: "44444444-4444-4444-4444-444444444444",
  agreement_id: agreement.id,
  state: "failed",
  attempt_count: 1,
  failure_category: "parser",
  failure_message: "Unable to read source",
  next_retry_at: null,
  queued_at: "2026-07-31T09:00:00Z",
  processing_started_at: "2026-07-31T09:01:00Z",
  completed_at: null,
  failed_at: "2026-07-31T09:02:00Z",
  created_at: "2026-07-31T09:00:00Z",
  updated_at: "2026-07-31T09:02:00Z",
  retry_permitted: true,
};

const analysisWithRisk: DocumentAnalysis = {
  schema_version: "document-analysis.v1",
  pipeline_version: "sprint-2.v1",
  diagnostics: [],
  classification: null,
  clauses: [],
  risks: [
    {
      severity: "high",
      explanation: "Termination notice requirements are unclear.",
      citation_anchor_ids: ["citation-a"],
    },
  ],
  summaries: {},
  document: {
    pages: [
      {
        number: 1,
        blocks: [
          {
            anchor_id: "citation-a",
            kind: "paragraph",
            text: "Termination is permitted on notice.",
          },
        ],
      },
    ],
  },
  analysis_provenance: {
    mode: "hybrid",
    model: "gpt-5.4-mini",
  },
};

describe("AgreementDetail", () => {
  it("shows agreement metadata, an accessible processing timeline, and a safe DOCX download", () => {
    render(
      <AgreementDetail
        agreement={agreement}
        documentUrl="/api/documents/download?object_key=tenant%2Fdocument.docx"
        processingJob={job}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Master services agreement" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: "Processing timeline" }),
    ).toHaveTextContent("Failed");
    expect(
      screen.getByRole("link", { name: "Download original DOCX" }),
    ).toHaveAttribute(
      "href",
      "/api/documents/download?object_key=tenant%2Fdocument.docx",
    );
    expect(
      screen.getByRole("button", { name: "Retry processing" }),
    ).toBeInTheDocument();
  });

  it("embeds PDFs with a labelled document viewer", () => {
    render(
      <AgreementDetail
        agreement={{
          ...agreement,
          files: [
            {
              ...agreement.files[0],
              file_name: "msa.pdf",
              content_type: "application/pdf",
            },
          ],
        }}
        documentUrl="/api/documents/download?object_key=tenant%2Fdocument.pdf"
      />,
    );

    expect(screen.getByTitle("PDF document viewer")).toHaveAttribute(
      "src",
      "/api/documents/download?object_key=tenant%2Fdocument.pdf",
    );
  });

  it("offers a start-analysis action for an uploaded agreement without a job", () => {
    render(
      <AgreementDetail agreement={agreement} startAnalysisAction={() => {}} />,
    );

    expect(
      screen.getByRole("button", { name: "Start analysis" }),
    ).toBeInTheDocument();
  });

  it("shows a cited high risk and analysis provenance", () => {
    render(
      <AgreementDetail agreement={agreement} analysis={analysisWithRisk} />,
    );

    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View source evidence" }),
    ).toHaveAttribute("href", "#evidence-citation-a");
    expect(screen.getByText(/gpt-5.4-mini/)).toBeInTheDocument();
  });

  it("renders a legacy analysis artifact without hybrid fields", () => {
    const legacyAnalysis = { ...analysisWithRisk };
    delete legacyAnalysis.risks;
    delete legacyAnalysis.analysis_provenance;

    render(<AgreementDetail agreement={agreement} analysis={legacyAnalysis} />);

    expect(
      screen.getByRole("heading", { name: "Document understanding" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Analysis provenance")).not.toBeInTheDocument();
  });
});
