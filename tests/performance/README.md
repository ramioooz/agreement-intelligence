# Local performance checks

These opt-in k6 scenarios measure the local container stack with synthetic data. They are engineering baselines, not production capacity claims.

1. Start the stack and obtain a bearer token for a seeded user.
2. Export `PERFORMANCE_ACCESS_TOKEN`, `PERFORMANCE_ORGANIZATION_ID`, and `PERFORMANCE_WORKSPACE_ID`.
3. Optionally export `PERFORMANCE_AGREEMENT_ID` and `PERFORMANCE_INCLUDE_UPLOAD=true`.
4. To measure workflow-decision acknowledgement, prepare a synthetic review whose
   active stage is assigned to the token's user and export
   `PERFORMANCE_REVIEW_ID`. The runner submits exactly one fresh decision for that
   review. Create a new disposable review before each additional sample; replayed
   idempotent reads are intentionally excluded from workflow latency evidence.
   `PERFORMANCE_WORKFLOW_DECISION` defaults to `approve`.
   Set `PERFORMANCE_SKIP_QUESTIONS=true` to isolate this acknowledgement objective
   from provider-dependent Q&A latency. A review ID is required in that mode.
5. Run `PERFORMANCE_TEST_CONFIRM=synthetic make performance-local`.

Every scenario validates authentication, tenant scope, response status, and the minimum response shape before evaluating latency. Summaries are written under `artifacts/performance/`; bearer tokens and document content are not written there.

Repository reads, uploads, and workflow decisions are synchronous acceptance
measures. Document processing and Q&A provider work are asynchronous or
provider-dependent. Queue-to-processing-start is measured by the isolated worker
restart scenario, which creates a real processing job and requires processing to
start within five seconds after the message is published.
