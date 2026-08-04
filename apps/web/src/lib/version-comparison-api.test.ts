import { describe, expect, it, vi } from "vitest";

import {
  createVersionComparison,
  getVersionComparison,
} from "@/lib/version-comparison-api";

const scope = { organizationId: "org", workspaceId: "workspace" };

describe("version comparison API client", () => {
  it("submits scoped comparison selections with an idempotency key", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "comparison-1" }), { status: 202 }),
      );
    await createVersionComparison({
      scope,
      agreementId: "agreement-1",
      baselineVersionId: "v1",
      targetVersionId: "v2",
      idempotencyKey: "request-1",
      fetcher,
    });
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining("organization_id=org"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": "request-1" }),
        body: JSON.stringify({
          baseline_version_id: "v1",
          target_version_id: "v2",
        }),
      }),
    );
  });

  it("loads a persisted comparison and surfaces failures", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "comparison-1",
          state: "completed",
          changes: [],
        }),
        { status: 200 },
      ),
    );
    await expect(
      getVersionComparison({
        scope,
        agreementId: "agreement-1",
        comparisonId: "comparison-1",
        fetcher,
      }),
    ).resolves.toMatchObject({ state: "completed" });
    fetcher.mockResolvedValue(
      new Response(JSON.stringify({ detail: "forbidden" }), { status: 403 }),
    );
    await expect(
      getVersionComparison({
        scope,
        agreementId: "agreement-1",
        comparisonId: "comparison-1",
        fetcher,
      }),
    ).rejects.toMatchObject({ status: 403 });
  });
});
