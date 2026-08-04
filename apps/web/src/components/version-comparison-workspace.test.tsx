import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VersionComparisonWorkspace } from "@/components/version-comparison-workspace";

const versions = [
  {
    id: "v1",
    agreement_id: "a",
    organization_id: "o",
    workspace_id: "w",
    version_number: 1,
    predecessor_version_id: null,
    file: {
      file_name: "old.pdf",
      content_type: "application/pdf",
      storage_key: "old",
      checksum: "old-checksum",
      byte_size: 1,
      version_number: 1,
    },
    uploaded_by: "u",
    uploaded_at: "2026-01-01T00:00:00Z",
    processing_state: "completed" as const,
    processing_job_id: "j1",
    extraction_version: "v1",
    analysis_provenance: {},
  },
  {
    id: "v2",
    agreement_id: "a",
    organization_id: "o",
    workspace_id: "w",
    version_number: 2,
    predecessor_version_id: "v1",
    file: {
      file_name: "new.pdf",
      content_type: "application/pdf",
      storage_key: "new",
      checksum: "new-checksum",
      byte_size: 1,
      version_number: 2,
    },
    uploaded_by: "u",
    uploaded_at: "2026-01-02T00:00:00Z",
    processing_state: "completed" as const,
    processing_job_id: "j2",
    extraction_version: "v1",
    analysis_provenance: {},
  },
];

describe("version comparison workspace", () => {
  it("renders selectors, structured panes, labels, filters, and citations", () => {
    render(
      <VersionComparisonWorkspace
        versions={versions}
        baselineAnalysis={
          {
            document: {
              pages: [
                {
                  number: 1,
                  blocks: [
                    {
                      anchor_id: "old-anchor",
                      kind: "paragraph",
                      text: "Old liability wording",
                    },
                  ],
                },
              ],
            },
          } as never
        }
        targetAnalysis={
          {
            document: {
              pages: [
                {
                  number: 1,
                  blocks: [
                    {
                      anchor_id: "new-anchor",
                      kind: "paragraph",
                      text: "New liability wording",
                    },
                  ],
                },
              ],
            },
          } as never
        }
        comparison={{
          id: "c",
          agreement_id: "a",
          baseline_version_id: "v1",
          target_version_id: "v2",
          processing_job_id: "j",
          analysis_version: "v1",
          state: "completed",
          failure_category: null,
          failure_message: null,
          analysis_provenance: {},
          created_at: "",
          updated_at: "",
          completed_at: "",
          changes: [
            {
              id: "change",
              ordinal: 1,
              alignment_kind: "matched",
              baseline_element_ids: ["old-anchor"],
              target_element_ids: ["new-anchor"],
              baseline_citation_ids: ["old-anchor"],
              target_citation_ids: ["new-anchor"],
              word_diff: [
                { operation: "delete", text: "Old" },
                { operation: "insert", text: "New" },
              ],
              confidence: 0.7,
              review_required: true,
              severity: "high",
              legal_concepts: ["liability"],
              rationale: "Liability wording changed",
              provider_provenance: {},
            },
          ],
        }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Compare agreement versions" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Baseline version")).toBeInTheDocument();
    expect(screen.getByLabelText("Target version")).toBeInTheDocument();
    expect(screen.getByText("Liability wording changed")).toBeInTheDocument();
    expect(screen.getByText("Review required")).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /View .* citation/ }),
    ).toHaveLength(2);
  });
});
