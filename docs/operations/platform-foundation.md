# AI platform foundation

The local stack now includes three deliberately separate capabilities:

- **SQS/LocalStack** remains the durable document-processing boundary.
- **Redis** is ephemeral coordination for tenant rate limits, budgets, short-lived
  result caching, and distributed locks. It must never become a second job queue.
- **OpenTelemetry Collector** receives operational spans from the API and worker.
  Instrumentation must attach only tenant-safe IDs, operation names, latency,
  token/cost totals, and retrieval/citation counts. Raw agreement text, prompts,
  provider output, credentials, and email are redacted.

The collector currently exports to its local debug exporter so the stack remains
portable without a SaaS account. Set `LANGFUSE_OTLP_ENDPOINT` and add a reviewed
collector exporter when a self-hosted Langfuse deployment is available; the
application contract remains OTLP and does not depend on Langfuse internals.

Run `make terraform-check` to validate the LocalStack-compatible Terraform module.
Use the migration runbook in `infra/terraform/README.md` for real AWS. LocalStack
validation does not prove production IAM, networking, ECS, RDS, ALB, WAF, or
identity-federation behavior.
