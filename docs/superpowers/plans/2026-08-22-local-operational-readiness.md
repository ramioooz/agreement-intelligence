# Local Operational Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove predictable local behavior under load and dependency failures, provide tested local recovery procedures, and validate the AWS-compatible infrastructure boundary without incurring cloud cost.

**Architecture:** Exercise the existing containerized stack and durable SQS/PostgreSQL workflows using isolated synthetic data. Backup scripts capture PostgreSQL and LocalStack object data with manifests/checksums; Terraform targets LocalStack for resource verification while real AWS apply remains deferred.

**Tech Stack:** Docker Compose, pytest, Playwright, k6, PostgreSQL tools, AWS CLI/LocalStack, Terraform, terraform-local, Checkov, shell contract tests.

**Spec:** `docs/superpowers/specs/2026-08-22-local-public-release-design.md`

## Global Constraints

- Performance tests use synthetic tenants and agreements.
- Failure tests must not reset or delete the developer’s ordinary volumes.
- Destructive restore validation uses a uniquely named disposable Compose project and explicit confirmation.
- Backup archives never contain `.env`, credentials, provider keys, tokens, or Keycloak administrator passwords.
- Terraform `apply` targets LocalStack only in automated/local verification.
- Real AWS plan/apply, federation, and managed disaster-recovery exercises remain in the deferred epic.

---

### Task 1: Define SLOs and performance scenarios (#51)

**Files:**
- Create: `tests/performance/k6/common.js`
- Create: `tests/performance/k6/repository.js`
- Create: `tests/performance/k6/search.js`
- Create: `tests/performance/k6/questions.js`
- Create: `tests/performance/run-local.sh`
- Create: `tests/performance/README.md`
- Create: `docs/operations/service-objectives.md`
- Create: `docs/evaluation/local-performance-baseline.md`
- Modify: `Makefile`

**Interfaces:**
- Produces: machine-readable k6 summary plus accepted local SLO report
- Consumes: seeded synthetic identities, API base URL, bearer tokens supplied at runtime, and generated test agreement IDs

- [ ] **Step 1: Define measurable local objectives**

Document p95 targets for repository reads, filtered search, accepted Q&A submission, upload acceptance, queue-to-processing start, and workflow decision acknowledgement. Separate synchronous latency from asynchronous completion time.

- [ ] **Step 2: Write the performance scenarios**

Use environment-supplied tokens and synthetic resource IDs. Each scenario asserts authorization, status, response schema, and tenant identity before including latency in results. Do not store tokens in the generated summary.

- [ ] **Step 3: Add `make performance-local`**

The command runs a pinned k6 container on the Compose network, writes JSON output under ignored `artifacts/performance/`, and refuses to start unless `PERFORMANCE_TEST_CONFIRM=synthetic` is set.

- [ ] **Step 4: Run the baseline**

```bash
PERFORMANCE_TEST_CONFIRM=synthetic make performance-local
```

Expected: thresholds pass or the report records the measured miss as a release finding with an issue; no result is silently excluded.

- [ ] **Step 5: Commit**

```bash
git add tests/performance docs/operations/service-objectives.md docs/evaluation/local-performance-baseline.md Makefile
git commit -m "test: add local performance objectives"
```

### Task 2: Exercise concurrency and failure recovery (#51)

**Files:**
- Create: `tests/resilience/test-duplicate-delivery.py`
- Create: `tests/resilience/test-worker-restart.sh`
- Create: `tests/resilience/test-provider-timeout.py`
- Create: `tests/resilience/test-queue-backlog.sh`
- Create: `tests/resilience/test-database-interruption.sh`
- Create: `tests/resilience/README.md`
- Modify: `apps/worker/tests/test_processing.py`
- Modify: `apps/worker/tests/test_workflow_checkpointing.py`
- Modify: `docs/evaluation/local-performance-baseline.md`

**Interfaces:**
- Consumes: existing idempotency keys, processing jobs, outbox records, SQS messages, and LangGraph checkpoint IDs
- Produces: repeatable evidence for duplicate delivery, restart, timeout, backlog, and database interruption behavior

- [ ] **Step 1: Add deterministic duplicate tests**

Publish the same processing/workflow message twice and assert one artifact set, one stage transition, one notification per assignee, and one final package.

- [ ] **Step 2: Add isolated container failure scripts**

Each shell test creates its own Compose project name and temporary `.env`, seeds synthetic data, stops only the targeted service, verifies the user-visible state, restarts it, and verifies recovery.

- [ ] **Step 3: Add provider timeout tests**

Inject a gateway that raises the existing unavailable error, assert bounded retry, safe persisted failure, lexical search availability, and no falsely completed provider artifact.

- [ ] **Step 4: Verify focused tests**

```bash
uv run pytest tests/resilience/test-duplicate-delivery.py tests/resilience/test-provider-timeout.py apps/worker/tests/test_processing.py apps/worker/tests/test_workflow_checkpointing.py -v
tests/resilience/test-worker-restart.sh
tests/resilience/test-queue-backlog.sh
tests/resilience/test-database-interruption.sh
```

Expected: recovery completes without duplicate durable effects.

- [ ] **Step 5: Record capacity and residual risks**

Update the baseline with queue drain rate, observed recovery time, failure state, and accepted local limitations. Link provider historical backfill limitations to #195.

- [ ] **Step 6: Commit**

```bash
git add tests/resilience apps/worker/tests docs/evaluation/local-performance-baseline.md
git commit -m "test: validate local failure recovery"
```

### Task 3: Implement tested local backup and restore (#52)

**Files:**
- Create: `scripts/backup-local.sh`
- Create: `scripts/restore-local.sh`
- Create: `tests/operations/test-backup-restore.sh`
- Create: `docs/operations/backup-restore.md`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- Produces: versioned backup directory with PostgreSQL custom-format dump, S3 object archive, inventory manifest, checksums, and safe configuration schema
- Consumes: running local stack, explicit output/input directory, and `CONFIRM=restore` for destructive restoration

- [ ] **Step 1: Write the failing contract test**

Assert `make backup-local` creates `manifest.json`, `postgres.dump`, `objects.tar`, and `SHA256SUMS`; assert restore refuses without confirmation and rejects checksum mismatch.

- [ ] **Step 2: Run and confirm failure**

```bash
tests/operations/test-backup-restore.sh
```

Expected: failure because scripts and Make targets do not exist.

- [ ] **Step 3: Implement backup**

`backup-local.sh` resolves explicit container names through Compose, runs `pg_dump --format=custom`, copies only the configured S3 bucket, records schema/migration version and object inventory, writes SHA-256 checksums, and sets restrictive local permissions. It refuses a destination inside tracked repository paths except ignored `artifacts/backups/`.

- [ ] **Step 4: Implement restore**

`restore-local.sh` validates manifest version and all checksums, requires `CONFIRM=restore`, restores into the current explicitly named Compose project, reloads objects, runs migrations, and calls `make stack-check`. It never reads or writes `.env` secrets in the archive.

- [ ] **Step 5: Verify in a disposable stack**

The contract test uploads a synthetic agreement, backs up, removes the disposable volumes, recreates the stack, restores, and verifies metadata, source checksum, object availability, and tenant authorization.

- [ ] **Step 6: Commit**

```bash
git add scripts/backup-local.sh scripts/restore-local.sh tests/operations/test-backup-restore.sh docs/operations/backup-restore.md Makefile .gitignore
git commit -m "feat: add tested local backup and restore"
```

### Task 4: Complete operational runbooks (#52)

**Files:**
- Create: `docs/operations/runbooks/stuck-processing.md`
- Create: `docs/operations/runbooks/provider-outage.md`
- Create: `docs/operations/runbooks/queue-backlog.md`
- Create: `docs/operations/runbooks/bad-model-release.md`
- Create: `docs/operations/runbooks/compromised-credential.md`
- Create: `docs/operations/runbooks/tenant-access-incident.md`
- Create: `docs/operations/runbooks/index.md`
- Modify: `docs/operations/platform-foundation.md`

**Interfaces:**
- Consumes: implemented stack commands, status APIs, audit records, configuration registry, and backup/restore scripts
- Produces: executable diagnosis, containment, recovery, evidence, and escalation paths

- [ ] **Step 1: Write each runbook using one template**

Every runbook contains trigger, impact, safe diagnostics, containment, recovery, verification, evidence, escalation, and residual risk. Commands must reference real Make targets, containers, APIs, and files.

- [ ] **Step 2: Define local RPO/RTO**

State the tested backup interval assumption, measured restore time, acceptable metadata/object loss window, and the fact that AWS RPO/RTO is unvalidated and deferred.

- [ ] **Step 3: Dry-run every safe command**

Run read-only/status commands against the stack. Run destructive recovery commands only in the disposable backup/restore project.

- [ ] **Step 4: Verify formatting and links**

```bash
pnpm exec prettier --check docs/operations
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add docs/operations
git commit -m "docs: add local operations runbooks"
```

### Task 5: Strengthen Terraform and LocalStack verification (#53 local scope)

**Files:**
- Modify: `infra/terraform/main.tf`
- Modify: `infra/terraform/providers.tf`
- Modify: `infra/terraform/variables.tf`
- Create: `infra/terraform/outputs.tf`
- Create: `infra/terraform/local.auto.tfvars.example`
- Create: `tests/infra/test-localstack-provisioning.sh`
- Create: `infra/terraform/checkov.yaml`
- Modify: `tests/infra/test-terraform-contract.sh`
- Modify: `infra/terraform/README.md`
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/ci/test-ci-workflow.sh`

**Interfaces:**
- Produces: locally provisioned S3 bucket, processing queue/DLQ, notification queue/DLQ, export queue/DLQ, and Secrets Manager-compatible secret
- Consumes: LocalStack endpoint with test credentials and no real AWS account

- [ ] **Step 1: Write infrastructure contract failures**

Assert all local queues, redrive policies, bucket protections supported by LocalStack, secret resource, outputs, and `use_localstack=true` endpoint overrides exist.

- [ ] **Step 2: Extend cloud-valid resources without live apply**

Move existing output blocks from `infra/terraform/main.tf` into `infra/terraform/outputs.tf`. Keep modules provider-compatible, encryption settings explicit, `force_destroy` limited to LocalStack, and names environment-scoped. Do not add ECS/RDS/ALB/WAF/Cognito resources to the local completion PR.

- [ ] **Step 3: Make LocalStack provisioning mandatory**

Install/use terraform-local in CI, run `tflocal plan` and `tflocal apply -auto-approve` against the CI LocalStack service, verify resources with AWS-compatible CLI calls, and destroy the emulated resources after the test.

- [ ] **Step 4: Add policy and security checks**

Run `terraform fmt -check`, `terraform validate`, Checkov with reviewed local-emulator exceptions, and the LocalStack provisioning test. Any skip must fail rather than silently pass.

- [ ] **Step 5: Verify**

```bash
make terraform-check
tests/infra/test-localstack-provisioning.sh
tests/ci/test-ci-workflow.sh
```

Expected: all checks exit zero without AWS credentials or cloud charges.

- [ ] **Step 6: Document migration boundary**

Describe remote state, reviewed plan, owner-controlled apply, staging smoke test, and optional cleanup. Explicitly list ECS/RDS/ALB/WAF/IAM/network/federation behaviors not proven locally.

- [ ] **Step 7: Commit**

```bash
git add infra/terraform tests/infra Makefile .github/workflows/ci.yml tests/ci/test-ci-workflow.sh
git commit -m "test: validate infrastructure with LocalStack"
```
