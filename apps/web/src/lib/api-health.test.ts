import { describe, expect, it, vi } from "vitest";

import { getApiConnectionStatus } from "@/lib/api-health";

describe("getApiConnectionStatus", () => {
  it("returns connected for the expected healthy contract", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ok",
          service: "api",
          version: "0.1.0",
        }),
        { status: 200 },
      ),
    );

    await expect(getApiConnectionStatus({ fetcher })).resolves.toBe(
      "connected",
    );
  });

  it("sends a correlation ID to the API health check", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ok",
          service: "api",
          version: "0.1.0",
        }),
        { status: 200 },
      ),
    );

    await getApiConnectionStatus({
      correlationId: "browser-correlation-id",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/health/ready",
      expect.objectContaining({
        headers: { "X-Correlation-ID": "browser-correlation-id" },
      }),
    );
  });

  it("returns unavailable when the API cannot be reached", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("connection refused"));

    await expect(getApiConnectionStatus({ fetcher })).resolves.toBe(
      "unavailable",
    );
  });

  it("returns unavailable for an invalid health response", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" })));

    await expect(getApiConnectionStatus({ fetcher })).resolves.toBe(
      "unavailable",
    );
  });
});
