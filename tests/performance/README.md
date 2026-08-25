# Local performance checks

These opt-in k6 scenarios measure the local container stack with synthetic data. They are engineering baselines, not production capacity claims.

1. Start the stack and obtain a bearer token for a seeded user.
2. Export `PERFORMANCE_ACCESS_TOKEN`, `PERFORMANCE_ORGANIZATION_ID`, and `PERFORMANCE_WORKSPACE_ID`.
3. Optionally export `PERFORMANCE_AGREEMENT_ID` and `PERFORMANCE_INCLUDE_UPLOAD=true`.
4. Run `PERFORMANCE_TEST_CONFIRM=synthetic make performance-local`.

Every scenario validates authentication, tenant scope, response status, and the minimum response shape before evaluating latency. Summaries are written under `artifacts/performance/`; bearer tokens and document content are not written there.

Repository reads and uploads are synchronous acceptance measures. Document processing and Q&A provider work are asynchronous or provider-dependent; queue-start and recovery timing are measured by the isolated resilience harnesses instead of being mixed into HTTP response-time claims.
