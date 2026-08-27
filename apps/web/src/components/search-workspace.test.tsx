import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SearchWorkspace } from "@/components/search-workspace";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const result = {
  agreement_id: "55555555-5555-5555-5555-555555555555",
  agreement_title: "Master services agreement",
  agreement_type: "client_agreement",
  agreement_status: "active",
  content_preview: "Either party may terminate with thirty days' notice.",
  citation: {
    chunk_id: "chunk-1",
    anchor_ids: ["anchor-termination"],
    source_checksum: "checksum",
    source_version: "1",
  },
  navigation: {
    agreement_id: "55555555-5555-5555-5555-555555555555",
    anchor_ids: ["anchor-termination"],
  },
  lexical_rank: 1,
  semantic_rank: 2,
  fused_score: 0.03,
  index_provenance: {
    build_id: "66666666-6666-6666-6666-666666666666",
    chunker_version: "chunker-v1",
    source_checksum: "checksum",
    embedding_index_version: "embedding-v1",
  },
};

describe("SearchWorkspace", () => {
  it("renders cited results with source navigation and index provenance", () => {
    render(
      <SearchWorkspace initialQuery="termination rights" results={[result]} />,
    );

    expect(
      screen.getByRole("heading", { name: "Grounded search" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Master services agreement")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View source evidence" }),
    ).toHaveAttribute(
      "href",
      "/dashboard/agreements/55555555-5555-5555-5555-555555555555#evidence-anchor-termination",
    );
    expect(screen.getByLabelText("Index: embedding-v1")).toBeInTheDocument();
  });

  it("keeps an explicit insufficient-evidence answer rather than inventing a response", () => {
    render(
      <SearchWorkspace
        initialQuery="termination rights"
        qaState={{
          state: "insufficient_evidence",
          message: "No authorized evidence supports that answer.",
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "No authorized evidence supports that answer.",
    );
  });

  it("submits a portfolio query through the URL without exposing source text", () => {
    render(<SearchWorkspace initialQuery="" />);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
      target: { value: "termination rights" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(push).toHaveBeenCalledWith("/dashboard/search?q=termination+rights");
  });

  it("exposes portfolio filters and preserves their values in the search URL", () => {
    render(<SearchWorkspace initialQuery="termination rights" />);

    fireEvent.change(screen.getByLabelText("Agreement type"), {
      target: { value: "client_agreement" },
    });
    fireEvent.change(screen.getByLabelText("Party"), {
      target: { value: "Example Counterparty" },
    });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "active" },
    });
    fireEvent.change(screen.getByLabelText("Updated after"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.change(screen.getByLabelText("Updated before"), {
      target: { value: "2026-01-31" },
    });
    fireEvent.change(screen.getByLabelText("Source version"), {
      target: { value: "v3" },
    });
    fireEvent.change(screen.getByLabelText("Agreement IDs"), {
      target: {
        value:
          "55555555-5555-5555-5555-555555555555, 66666666-6666-6666-6666-666666666666",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(push).toHaveBeenLastCalledWith(
      "/dashboard/search?q=termination+rights&agreement_type=client_agreement&party=Example+Counterparty&status=active&updated_after=2026-01-01&updated_before=2026-01-31&source_version=v3&agreement_id=55555555-5555-5555-5555-555555555555&agreement_id=66666666-6666-6666-6666-666666666666",
    );
  });

  it("states honestly when no reviewer-approved information is available", () => {
    render(<SearchWorkspace initialQuery="termination rights" />);

    expect(
      screen.getByText(/No reviewer-approved information matched this search/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Sprint 6/i)).not.toBeInTheDocument();
  });

  it("creates a new scoped question thread after restarting a search", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "replacement-thread", turns: [] }), {
          status: 201,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "turn-1",
            question: "What are the termination rights?",
            answer: {
              status: "insufficient_evidence",
              message: "No authorized evidence supports that answer.",
              claims: [],
            },
            created_at: "2026-08-04T00:00:00Z",
          }),
          { status: 201 },
        ),
      );

    render(
      <SearchWorkspace
        initialQuery="termination rights"
        thread={{
          id: "stale-thread",
          organization_id: "organization",
          workspace_id: "workspace",
          agreement_ids: null,
          turns: [],
        }}
      />,
    );
    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
      target: { value: "notice period" },
    });
    fireEvent.change(screen.getByLabelText("Agreement IDs"), {
      target: {
        value:
          "55555555-5555-5555-5555-555555555555, 66666666-6666-6666-6666-666666666666",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), {
      target: { value: "What are the termination rights?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask question" }));

    await screen.findByText("No authorized evidence supports that answer.");
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/questions/threads",
      expect.objectContaining({
        body: JSON.stringify({
          agreement_ids: [
            "55555555-5555-5555-5555-555555555555",
            "66666666-6666-6666-6666-666666666666",
          ],
        }),
        method: "POST",
      }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/questions/threads/replacement-thread/turns",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("submits a question through the scoped thread adapter", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "thread-1", turns: [] }), {
          status: 201,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "turn-1",
            question: "What are the termination rights?",
            answer: {
              status: "answered",
              message: "Either party may terminate with notice.",
              claims: [
                {
                  text: "Either party may terminate with notice.",
                  citations: [
                    {
                      agreement_id: "55555555-5555-5555-5555-555555555555",
                      anchor_id: "anchor-termination",
                      supporting_quote:
                        "Either party may terminate with thirty days' notice.",
                      source_checksum: "sha256:example",
                      source_version: "3",
                    },
                  ],
                },
              ],
            },
            created_at: "2026-08-04T00:00:00Z",
          }),
          { status: 201 },
        ),
      );

    render(<SearchWorkspace initialQuery="termination rights" />);
    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), {
      target: { value: "What are the termination rights?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask question" }));

    expect(
      await screen.findByText("Either party may terminate with notice."),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "View source evidence" }),
    ).toHaveAttribute(
      "href",
      "/dashboard/agreements/55555555-5555-5555-5555-555555555555#evidence-anchor-termination",
    );
    expect(
      screen.getByText("Source version 3 · sha256:example"),
    ).toBeInTheDocument();
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/questions/threads",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/questions/threads/thread-1/turns",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
