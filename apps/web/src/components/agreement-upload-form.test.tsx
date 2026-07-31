import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgreementUploadForm } from "@/components/agreement-upload-form";

describe("AgreementUploadForm", () => {
  it("submits the selected agreement file through the same-origin upload route", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "agreement-1" }), { status: 201 }),
      );
    render(<AgreementUploadForm fetcher={fetcher} />);

    fireEvent.change(screen.getByLabelText("Agreement title"), {
      target: { value: "Master services agreement" },
    });
    fireEvent.change(screen.getByLabelText("Agreement type"), {
      target: { value: "services" },
    });
    fireEvent.change(screen.getByLabelText("Original agreement file"), {
      target: {
        files: [new File(["pdf"], "msa.pdf", { type: "application/pdf" })],
      },
    });
    fireEvent.submit(
      screen.getByRole("button", { name: "Upload agreement" }).closest("form")!,
    );

    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(fetcher).toHaveBeenCalledWith(
      "/api/agreements/upload",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Agreement uploaded.");
  });
});
