import { describe, expect, it, vi } from "vitest";

import {
  getDocumentAnalysis,
  listAgreements,
  uploadAgreementVersion,
  uploadDocument,
  type AgreementScope,
} from "@/lib/agreement-api";
import {
  getProcessingJob,
  retryProcessingJob,
  submitProcessingJob,
} from "@/lib/processing-api";

const scope: AgreementScope = {
  organizationId: "11111111-1111-1111-1111-111111111111",
  workspaceId: "22222222-2222-2222-2222-222222222222",
};

describe("agreement API client", () => {
  it("loads analysis from the processing job bound to an evaluation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: "document-analysis.v1",
          document: { pages: [] },
        }),
        { status: 200 },
      ),
    );

    await getDocumentAnalysis({
      baseUrl: "https://api.example.test",
      scope,
      agreementId: "55555555-5555-5555-5555-555555555555",
      processingJobId: "44444444-4444-4444-4444-444444444444",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/agreements/55555555-5555-5555-5555-555555555555/analysis?organization_id=11111111-1111-1111-1111-111111111111&workspace_id=22222222-2222-2222-2222-222222222222&processing_job_id=44444444-4444-4444-4444-444444444444",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("lists a scoped, filtered page with the caller token", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          page: { limit: 25, next_cursor: "25" },
        }),
        { status: 200 },
      ),
    );

    const result = await listAgreements({
      baseUrl: "https://api.example.test",
      scope,
      token: "access-token",
      query: "master services",
      status: "active",
      cursor: "0",
      fetcher,
    });

    expect(result.page.next_cursor).toBe("25");
    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/agreements?organization_id=11111111-1111-1111-1111-111111111111&workspace_id=22222222-2222-2222-2222-222222222222&limit=25&cursor=0&status=active&query=master+services",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
        }),
      }),
    );
  });

  it("uploads only through the scoped document endpoint", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          document_id: "33333333-3333-3333-3333-333333333333",
          tenant_id: scope.organizationId,
          workspace_id: scope.workspaceId,
          original_filename: "terms.pdf",
          content_type: "application/pdf",
          byte_size: 10,
          sha256: "abc",
          object_key: "tenants/111/workspaces/222/documents/abc/original.pdf",
          duplicate: false,
        }),
        { status: 201 },
      ),
    );

    await uploadDocument({
      baseUrl: "https://api.example.test",
      scope,
      token: "access-token",
      file: new File(["document"], "terms.pdf", { type: "application/pdf" }),
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/documents",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
        }),
      }),
    );
    const request = fetcher.mock.calls[0]?.[1];
    expect(request?.body).toBeInstanceOf(FormData);
    expect((request?.body as FormData).get("organization_id")).toBe(
      scope.organizationId,
    );
  });

  it("uploads a revision with optimistic concurrency and idempotency controls", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "66666666-6666-6666-6666-666666666666",
          version_number: 2,
        }),
        { status: 201 },
      ),
    );

    await uploadAgreementVersion({
      baseUrl: "https://api.example.test",
      scope,
      token: "access-token",
      agreementId: "55555555-5555-5555-5555-555555555555",
      expectedCurrentVersion: 1,
      idempotencyKey: "revision-123",
      file: new File(["revision"], "terms-v2.pdf", {
        type: "application/pdf",
      }),
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/agreements/55555555-5555-5555-5555-555555555555/versions",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
          "Idempotency-Key": "revision-123",
        }),
      }),
    );
    const request = fetcher.mock.calls[0]?.[1];
    expect((request?.body as FormData).get("expected_current_version")).toBe(
      "1",
    );
  });
});

describe("processing API client", () => {
  it("submits an idempotent processing job after agreement creation", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify(processingJob), { status: 202 }),
      );

    await submitProcessingJob({
      baseUrl: "https://api.example.test",
      scope,
      token: "access-token",
      agreementId: "55555555-5555-5555-5555-555555555555",
      idempotencyKey: "upload-123",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/agreements/55555555-5555-5555-5555-555555555555/processing-jobs?organization_id=11111111-1111-1111-1111-111111111111&workspace_id=22222222-2222-2222-2222-222222222222",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
          "Idempotency-Key": "upload-123",
        }),
      }),
    );
  });

  it("reads a processing job from its authorized scoped endpoint", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify(processingJob), { status: 200 }),
      );

    await getProcessingJob({
      baseUrl: "https://api.example.test",
      scope,
      token: "access-token",
      agreementId: "55555555-5555-5555-5555-555555555555",
      jobId: "44444444-4444-4444-4444-444444444444",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/agreements/55555555-5555-5555-5555-555555555555/processing-jobs/44444444-4444-4444-4444-444444444444?organization_id=11111111-1111-1111-1111-111111111111&workspace_id=22222222-2222-2222-2222-222222222222",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
        }),
      }),
    );
  });

  it("retries a job through its authorized scoped endpoint", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify(processingJob), { status: 202 }),
      );

    await retryProcessingJob({
      baseUrl: "https://api.example.test",
      scope,
      token: "access-token",
      agreementId: "55555555-5555-5555-5555-555555555555",
      jobId: "44444444-4444-4444-4444-444444444444",
      fetcher,
    });

    expect(fetcher).toHaveBeenCalledWith(
      "https://api.example.test/agreements/55555555-5555-5555-5555-555555555555/processing-jobs/44444444-4444-4444-4444-444444444444/retry?organization_id=11111111-1111-1111-1111-111111111111&workspace_id=22222222-2222-2222-2222-222222222222",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
        }),
      }),
    );
  });
});

const processingJob = {
  id: "44444444-4444-4444-4444-444444444444",
  agreement_id: "55555555-5555-5555-5555-555555555555",
  state: "queued",
  attempt_count: 2,
  failure_category: null,
  failure_message: null,
  next_retry_at: null,
  queued_at: "2026-07-31T09:00:00Z",
  processing_started_at: null,
  completed_at: null,
  failed_at: null,
  created_at: "2026-07-31T09:00:00Z",
  updated_at: "2026-07-31T09:00:00Z",
  retry_permitted: false,
};
