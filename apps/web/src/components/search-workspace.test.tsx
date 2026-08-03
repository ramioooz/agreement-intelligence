import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SearchWorkspace } from "@/components/search-workspace";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

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
              claims: [],
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
    fetcher.mockRestore();
  });
});
