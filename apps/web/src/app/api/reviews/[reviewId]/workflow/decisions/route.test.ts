import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth-session-token", () => ({
  applyRefreshedKeycloakSession: (response: Response) => response,
  getKeycloakAccessTokenResult: vi.fn(async () => ({
    accessToken: "synthetic-access-token",
  })),
}));

import { POST } from "@/app/api/reviews/[reviewId]/workflow/decisions/route";

describe("approval decision proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("forwards the configured organization and workspace scope", async () => {
    vi.stubEnv("API_ORGANIZATION_ID", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    vi.stubEnv("API_WORKSPACE_ID", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
    const fetchMock = vi.fn(async () =>
      Response.json({ state: "waiting_for_approval" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new Request(
      "http://localhost/api/reviews/review-1/workflow/decisions",
      {
        method: "POST",
        body: JSON.stringify({
          action: "approve",
          expected_revision: 0,
          idempotency_key: "synthetic-decision",
        }),
      },
    );

    await POST(request as never, {
      params: Promise.resolve({ reviewId: "review-1" }),
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/reviews/review-1/workflow/decisions?organization_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&workspace_id=bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
