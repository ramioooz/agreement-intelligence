# Local platform operations

This is the operator entry point for the complete Docker Compose application. It favors
non-destructive diagnosis and separates locally verified procedures from deferred AWS work.

## Contents

- [Service model](#service-model)
- [Configuration and startup](#configuration-and-startup)
- [Health and service discovery](#health-and-service-discovery)
- [Provider modes and recovery](#provider-modes-and-recovery)
- [Processing, queue, and worker recovery](#processing-queue-and-worker-recovery)
- [Data, backup, restore, and reset](#data-backup-restore-and-reset)
- [Observability, privacy, and retention](#observability-privacy-and-retention)
- [Terraform and LocalStack](#terraform-and-localstack)
- [Verification and release operations](#verification-and-release-operations)
- [Incident runbooks](#incident-runbooks)
- [Deferred cloud operations](#deferred-cloud-operations)

## Service model

The default project name is `agreement-intelligence`. All published ports bind to
`127.0.0.1`.

| Service | Port | State and responsibility |
| --- | ---: | --- |
| `web` | 3000 | Next.js OIDC session and product UI |
| `api` | 8000 | FastAPI domain/API/OpenAPI |
| `mcp` | 8001 | OIDC-protected read-only MCP tools |
| `keycloak` | 8080 | Local realm/client/demo users |
| `postgres` | 5432 | Application/Keycloak databases, pgvector, named volume |
| `redis` | 6379 | Ephemeral rate/budget/lock/cache coordination |
| `localstack` | 4566 | Ephemeral S3/SQS-compatible gateway |
| `otel-collector` | 4317/4318 | Safe OTLP gRPC/HTTP transport |
| `worker` | none | SQS processing, parsing, analysis, indexing |

`keycloak-bootstrap` and `localstack-bootstrap` are successful one-shot jobs.
`langfuse` and `llama-cpp` exist only under explicit profiles and are not default health
requirements.

PostgreSQL is the business source of truth. LocalStack S3 owns source/artifact bytes. SQS
wakes durable work. Redis must never become a second job queue or business ledger.

[Back to contents](#contents)

## Configuration and startup

```bash
cp .env.example .env
scripts/validate-stack-env.sh .env
docker compose --project-name agreement-intelligence --env-file .env config --quiet
make stack-up
make stack-check
```

Replace every placeholder before validation. Keep `.env` ignored. Required groups include
database names/users/passwords, OIDC realm/client/issuers/origin/session secret, demo users,
retention values, LocalStack resources/test credentials, and loopback ports. Provider and
compatible-model values remain optional.

If `WEB_PORT` changes, `WEB_PUBLIC_ORIGIN` and `AUTH_URL` must use the same port so
NextAuth and Keycloak callbacks agree. Recreate affected web/Keycloak/bootstrap services.

`make stack-up` runs `docker compose up --detach --build --wait --wait-timeout 180`.
Ordinary startup does not delete volumes.

[Back to contents](#contents)

## Health and service discovery

```bash
make stack-status
make stack-check
docker compose --project-name agreement-intelligence --env-file .env ps --all
```

`stack-check` verifies the exact running service set; health for web/API/worker/PostgreSQL/
LocalStack/Keycloak/Redis/MCP; OTel running; successful bootstrap jobs; pgvector; the
Keycloak database; S3/queue resources; realm/client/users; API liveness/Swagger/OpenAPI;
web-to-API connectivity; and worker startup.

| Probe | Meaning |
| --- | --- |
| <http://localhost:8000/health/live> | API process liveness |
| <http://localhost:8000/health/ready> | API dependency readiness |
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8000/openapi.json> | API contract |
| <http://localhost:3000> | Web plus visible API connection state |

For a failed service, inspect a bounded log tail:

```bash
docker compose --project-name agreement-intelligence --env-file .env logs \
  --tail 200 <service>
```

Do not paste raw logs into evidence until tokens, emails, document text, prompts, provider
output, local paths, and environment values are excluded.

[Back to contents](#contents)

## Provider modes and recovery

### No-key deterministic/lexical mode

Leave `OPENAI_API_KEY=` and compatible endpoint credentials empty. The complete stack
starts. Repository, deterministic parsing/rules, versions, playbooks, lexical search,
comparison, review/approval, audit, package, and MCP behavior remain available by role.
Embeddings, semantic retrieval, and generated answers are explicitly unavailable/degraded.

### Provider-powered mode

The operator adds a user-owned key only to ignored `.env`, confirms provider privacy/
retention/cost authorization, recreates API/worker, and runs:

```bash
make provider-smoke
make stack-check
```

`provider-smoke` is an opt-in external request and prints safe model, latency, usage, and
validation metadata only. It must not print the key, prompt, provider body, or document
content.

### Outage and recovery

Provider errors preserve deterministic artifacts and safe provenance; lexical search stays
available. Grounded answers return explicit unavailable/failure states. Diagnose account,
model, quota, compatible endpoint, network, and budgets without revealing the key. After
recovery, run smoke, process a new synthetic fixture, then manually retry/requeue/reprocess
authorized failed work.

New queries attempt query embeddings again. Complete automatic historical enrichment/
embedding backfill is not implemented. Follow the
[provider-outage runbook](runbooks/provider-outage.md).

[Back to contents](#contents)

## Processing, queue, and worker recovery

Inspect safe state first:

```bash
make stack-status
docker compose --project-name agreement-intelligence --env-file .env logs \
  --tail 200 api worker localstack
docker compose --project-name agreement-intelligence --env-file .env run --rm \
  localstack-bootstrap verify
```

Jobs have queued, processing, completed, and failed states plus attempt/reason metadata.
Authorized retry/requeue routes are safer than editing database/queue records. Restarting a
worker is non-destructive:

```bash
docker compose --project-name agreement-intelligence --env-file .env restart worker
make stack-check
```

The API commits an outbox row and attempts SQS publication immediately. A publish failure
leaves that row pending; the current local API has no autonomous outbox poller. After SQS
recovers, invoke an authorized retry/requeue or another same-scope processing action so its
dispatcher can replay pending rows. Restarting services alone does not guarantee replay.
Worker leases/idempotent writes protect redelivery. Acknowledge recovery only after the exact
agreement/version reaches a controlled terminal state, artifacts/citations persist, and
duplicates are absent.

Use [Stuck processing](runbooks/stuck-processing.md) or
[Queue backlog](runbooks/queue-backlog.md). Synthetic resilience scripts require explicit
isolated confirmation:

```bash
RESILIENCE_TEST_CONFIRM=isolated make resilience-local
```

They are not ordinary production commands and can interrupt disposable local dependencies.

[Back to contents](#contents)

## Data, backup, restore, and reset

Normal shutdown:

```bash
make stack-down
```

PostgreSQL's named volume is preserved. Default LocalStack state is ephemeral and resources
are recreated on startup.

Create a checksum-manifest backup to an explicit local directory:

```bash
make backup-local BACKUP_DIR=artifacts/backups/<timestamp>
```

Restore only after confirming the exact environment and backup:

```bash
make stack-status
make restore-local RESTORE_DIR=artifacts/backups/<timestamp> CONFIRM=restore
make stack-check
```

The locally measured assumption is a 24-hour RPO, with a 5-minute local RTO target; these
are not AWS or contractual objectives. Read [Backup and restore](backup-restore.md) for
scope, manifest/checksum behavior, exclusions, evidence, and isolated destructive rehearsal.

### Destructive reset

```bash
make stack-status
make stack-reset CONFIRM=reset
```

Reset deletes the selected Compose project's volumes and recreates the stack. The Make
target refuses to run without `CONFIRM=reset`. Back up first and verify
`STACK_PROJECT_NAME`; never use a broad or production project name.

[Back to contents](#contents)

## Observability, privacy, and retention

API, worker, and MCP export through the OpenTelemetry Collector. Allowed attributes are
operation/outcome, safe reason categories, opaque tenant-safe IDs, latency, retry, token/
cost totals, result counts, and workflow state. Raw document text, prompts, provider output,
credentials, emails, subjects/titles, request bodies, and raw identifiers are excluded
before exporter handoff.

The default collector uses a local debug exporter. Optional Langfuse requires reviewed local
secrets and an explicit profile:

```bash
docker compose --env-file .env -f compose.yaml -f compose.observability.yaml \
  --profile observability up --detach
```

See [Observability](observability.md). Langfuse remains a telemetry consumer, not the source
of truth for prompts, configuration, evaluation, or audit.

`AUDIT_RETENTION_DAYS`, `TELEMETRY_RETENTION_DAYS`, and
`APPLICATION_LOG_RETENTION_DAYS` are policy metadata. Immutable business audit records
are not automatically deleted. A production retention/legal-hold program is deployment
work, not supplied by the local demo.

[Back to contents](#contents)

## Terraform and LocalStack

Install the pinned CI versions of Terraform, terraform-local, and Checkov, then:

```bash
make terraform-check
make terraform-provision-local
```

`terraform-check` fails when a required tool is absent. It formats, initializes,
validates, applies policy/security checks, and exercises a LocalStack plan contract.
`terraform-provision-local` stages an allowlisted module, replaces ambient AWS credentials
with non-secret LocalStack values, applies, inspects resource/redrive behavior, and destroys
the disposable resources.

LocalStack evidence covers AWS-compatible API and Terraform wiring only. Read the
[Terraform migration runbook](../../infra/terraform/README.md) before any cloud proposal.

[Back to contents](#contents)

## Verification and release operations

Source quality:

Create owner-readable ignored `.env.release-test.local` in an editor as described in
[Getting started](../getting-started.md#9-verify-source-and-release-gates), then load it
without putting the database credential in a command argument:

```bash
make setup
chmod 600 .env.release-test.local
set -a
. ./.env.release-test.local
set +a
make check
unset AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL
```

The URL is mandatory because forced tenant-RLS integration may not be skipped. Never use
retained or production data.

Documentation and release:

```bash
node scripts/check-doc-links.mjs
tests/docs/test-documentation-contract.sh
make ai-eval
make release-check
```

`make release-check` is non-destructive and requires explicit disposable database and
running-stack configuration documented in [Release evidence](../testing/release-evidence.md).
It never invokes `stack-reset`. Provider smoke/assisted AI evaluation and the owner manual
pass remain separate opt-ins.

Use the combined [Manual QA and API guide](../testing/manual-test-plan.md) and
the [evidence template](../testing/evidence-template.md). Record safe commands, commit,
timestamp, pass/fail/blocked, counts/checksums, and cleanup—never credentials or content.

[Back to contents](#contents)

## Incident runbooks

The [runbook index](runbooks/index.md) covers:

- [provider outage](runbooks/provider-outage.md);
- [stuck processing](runbooks/stuck-processing.md);
- [queue backlog](runbooks/queue-backlog.md);
- [bad model/configuration release](runbooks/bad-model-release.md);
- [compromised credential](runbooks/compromised-credential.md); and
- [tenant-access incident](runbooks/tenant-access-incident.md).

Containment takes priority over diagnosis when credentials or cross-tenant access may be
involved. Preserve only safe evidence and use [Security policy](../../SECURITY.md) for
private reporting.

[Back to contents](#contents)

## Deferred cloud operations

No command here applies Terraform to AWS. Owner authorization, approved accounts/budgets,
secrets, and a reviewed migration are prerequisites. Real IAM/VPC/TLS/ALB/WAF, ECS/RDS,
managed Redis, federation, autoscaling, alarms, load/cost, backups, RPO/RTO, disaster
recovery, data residency, and incident response remain unvalidated.

Passing local checks is useful release evidence but never cloud deployment approval. See
[Roadmap](../roadmap.md) and the [Threat model](../security/threat-model.md).

[Back to top](#local-platform-operations)
