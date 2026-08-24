# Pre-publication security and architecture review

**Review completed:** 24 August 2026  
**Reviewed revision:** `376d5cc`  
**Scope:** local application, source repository, container stack, and emulated AWS boundaries  
**Verdict:** **Not ready to make public until the release blockers below are resolved and re-reviewed.**

This is a report-only review. It does not change application behavior. Every
finding has a dedicated GitHub issue and is attached to the Production Release
epic so remediation remains visible and reviewable.

## Contents

- [Executive summary](#executive-summary)
- [Verification performed](#verification-performed)
- [Findings](#findings)
- [Boundaries reviewed with no new finding](#boundaries-reviewed-with-no-new-finding)
- [Deferred real-AWS validation](#deferred-real-aws-validation)
- [Release recommendation](#release-recommendation)

## Executive summary

The platform has strong application-level authorization, evidence validation,
provider fallback, immutable version records, scoped object keys, and read-only
MCP boundaries. Locked dependency audits and a full-history secret scan were
clean. The main pre-publication risks are defense-in-depth gaps at the database
layer, incomplete permanent deletion, unbounded parsing of hostile documents,
and free-form audit values that can retain restricted data.

| Severity | Count | Meaning |
| --- | ---: | --- |
| Release blocker | 4 | Must be fixed and re-reviewed before the repository is made public. |
| High | 3 | Must be resolved before claiming production-grade local closure. |
| Improvement | 2 | Hardening already tracked in the release backlog. |
| Cloud deferred | 3 | Requires a real AWS environment and remains explicitly deferred. |

## Verification performed

| Check | Result | Notes |
| --- | --- | --- |
| `make check` | Passed with one environment exception | Formatting, lint, mypy (172 files), web tests, 407 Python tests (1 skipped), shell contracts, authentication contracts, and package builds passed. The sandbox denied Turbopack's loopback operation; the equivalent Next.js webpack production build passed. |
| `pnpm audit --prod --audit-level high` | Passed | No known production JavaScript vulnerabilities. |
| `uv run pip-audit` after `uv sync --all-packages` | Passed | No known Python vulnerabilities in the locked workspace environment. |
| `make terraform-check` | Partially exercised | Terraform format, initialization, and validation passed. The LocalStack plan was skipped because `tflocal` was unavailable and the script still returned success; see finding F-09. |
| Full-history Gitleaks scan | Passed | 182 commits and approximately 2.87 MB scanned with no detected secret. |
| Disposable PostgreSQL RLS contract | Passed, then expanded | The existing contract passed. A complete `pg_catalog` inventory exposed tenant tables outside that contract; see F-01. |
| Focused hostile-document reproduction | Failed safely at neither boundary | A 48,892-byte DOCX containing a 50,000,025-byte expanded XML entry passed upload validation; see F-03. |
| Focused audit-redaction reproduction | Failed | A secret-like value inside a generic `reason` field was stored verbatim; see F-04. |

## Findings

### F-01 — Release blocker: tenant RLS does not cover every scoped table

**Issue:** [#209 — Enforce tenant RLS across every scoped table](https://github.com/ramioooz/agreement-intelligence/issues/209)

**Evidence:** A disposable PostgreSQL inventory of every table containing
`organization_id` found 39 scoped tables. Only 19 had row-level security both
enabled and forced. Twenty tables—including approval policies, review cases,
assignments, workflow stages, workflow outbox records, final packages, version
comparisons, processing jobs, MCP audit records, and deletion audit records—had
neither flag. The worker also reads a processing job before establishing the
tenant GUC in
`apps/worker/src/agreement_intelligence_worker/processing.py:324`; tenant
configuration occurs later for an agreement-state update at line 554.

**Reproduction:** Start a disposable pgvector PostgreSQL instance, apply every
migration, and query `pg_class.relrowsecurity` and
`pg_class.relforcerowsecurity` for every ordinary table containing an
`organization_id` column. Compare that inventory with the current RLS contract.

**Risk:** An omitted workspace predicate, future query regression, or service
credential misuse is not contained by PostgreSQL on these tables. Because the
application and worker use the application database role, `FORCE ROW LEVEL
SECURITY` is part of the intended defense-in-depth boundary.

### F-02 — Release blocker: permanent deletion can leave historical sources and inconsistent state

**Issue:** [#210 — Make permanent agreement deletion complete and recoverable](https://github.com/ramioooz/agreement-intelligence/issues/210)

**Evidence:** The delete route removes object-storage keys before deleting the
database records (`apps/api/src/agreement_intelligence_api/agreements/routes.py:300`).
The object inventory in
`apps/api/src/agreement_intelligence_api/agreements/repository.py:188` derives
source keys from the agreement's current `files` value plus processing
artifacts. Uploading a new version replaces that `files` value with only the new
source (`apps/api/src/agreement_intelligence_api/agreements/versions.py:125`),
while immutable historical version rows retain separate storage keys.

**Reproduction:** Upload version 1, upload version 2, then permanently delete the
agreement. Inspect the LocalStack S3 prefix and compare every historical
`agreement_versions.storage_key` with the deletion inventory. Separately inject
an S3 or database failure between the two destructive operations.

**Risk:** Historical agreement material can survive a purported permanent
deletion. Conversely, an object-store success followed by database failure can
leave metadata pointing at missing evidence. Both outcomes undermine retention,
privacy, audit, and user expectations.

### F-03 — Release blocker: untrusted PDF and DOCX parsing has no expanded-resource bounds

**Issue:** [#211 — Bound resource usage for untrusted document parsing](https://github.com/ramioooz/agreement-intelligence/issues/211)

**Evidence:** Upload validation checks the request size and file signature, but
does not cap PDF page/object complexity or DOCX expanded size and member count.
The worker passes the complete byte array directly to `pypdf` or `python-docx`
and iterates every page, paragraph, and table in
`apps/worker/src/agreement_intelligence_worker/document_understanding.py:70`.

**Reproduction:** A synthetic DOCX compressed to 48,892 bytes with a
50,000,025-byte `word/document.xml` entry was accepted by the current validator.
Equivalent PDF stress cases can use excessive pages, deeply nested objects, or
expensive content streams.

**Risk:** A tenant-authorized upload can exhaust worker memory or CPU, block the
processing queue, and cause repeated redelivery. Container limits alone do not
provide a predictable business failure mode or protect queue capacity.

### F-04 — Release blocker: free-form audit values bypass sensitive-value redaction

**Issue:** [#213 — Redact restricted values from free-form audit reasons](https://github.com/ramioooz/agreement-intelligence/issues/213)

**Evidence:** `AuditEventWriter` redacts only when the metadata key contains a
sensitive fragment (`apps/api/src/agreement_intelligence_api/audit/service.py:18`
and line 132). Policy override text is recorded under the generic key `reason`
(`apps/api/src/agreement_intelligence_api/reviews/collaboration_routes.py:99`).
A direct reproduction retained `contact legal@example.test with token
sk-proj-demo-secret` unchanged in audit metadata.

**Reproduction:** Submit a policy override reason, deletion reason, comment, or
similar free-form value containing an email address, bearer token, or provider
key pattern. Read the stored audit event through PostgreSQL or the audit API.

**Risk:** Immutable audit storage can become a long-lived secondary store for
personal data and credentials, defeating the platform's otherwise explicit
telemetry and prompt-redaction controls.

### F-05 — High: processing outbox messages have no autonomous replay

**Issue:** [#51 — Improve performance, concurrency and failure recovery](https://github.com/ramioooz/agreement-intelligence/issues/51)

**Evidence:** `ProcessingOutboxDispatcher.dispatch_pending` stops when publishing
to SQS raises an exception (`apps/api/src/agreement_intelligence_api/processing/queue.py:63`).
The dispatcher is invoked from submission, retry, and requeue request paths; no
scheduled process continuously replays old undelivered records. Detailed review
evidence is attached to #51.

**Reproduction:** Make SQS unavailable while submitting an analysis job, restore
SQS, and perform no further API action. The database can retain an undelivered
outbox row while no queue message wakes the worker.

**Risk:** A transient queue outage can strand work indefinitely even after the
dependency recovers. This breaks the expected graceful-recovery behavior and
requires manual requeue or unrelated traffic.

### F-06 — High: final review package generation occurs inside read requests

**Issue:** [#212 — Generate and protect terminal review packages durably](https://github.com/ramioooz/agreement-intelligence/issues/212)

**Evidence:** Reading package metadata or a missing stored package calls
`_create_final_package` from GET handlers
(`apps/api/src/agreement_intelligence_api/reviews/workflow_routes.py:159` and
line 211). The handler writes object storage, database metadata, and audit state.
Immutability is enforced by SQLAlchemy event listeners in
`apps/api/src/agreement_intelligence_api/reviews/models.py:465`, rather than by a
database constraint or trigger that also protects non-ORM access.

**Reproduction:** Complete a review without fetching its package, verify that no
package exists, then make the first GET request. Observe that this read creates
the PDF, manifest, object-store records, database row, and audit event.

**Risk:** Read traffic owns a multi-system side effect, making retry, attribution,
latency, partial failure, and operational recovery harder. Database-level
immutability is not guaranteed outside the ORM.

### F-07 — High: CI does not exercise the complete tenant RLS inventory

**Issue:** [#209 — Enforce tenant RLS across every scoped table](https://github.com/ramioooz/agreement-intelligence/issues/209)

**Evidence:** The existing disposable-database RLS test passes, but it checks a
curated subset. The CI job in `.github/workflows/ci.yml` has no PostgreSQL
service and therefore cannot enforce a full migrated-schema inventory on every
pull request.

**Reproduction:** Add a new tenant-scoped table without an RLS policy. Run the
current CI-equivalent source checks; they remain green.

**Risk:** New tables can silently fall outside the database tenant boundary and
remain unnoticed until a separate manual audit.

### F-08 — Improvement: build inputs are not immutable and updates are not automated

**Issue:** [#214 — Pin build inputs and automate dependency updates](https://github.com/ramioooz/agreement-intelligence/issues/214)

**Evidence:** GitHub Actions use mutable major tags such as
`actions/checkout@v7`, `astral-sh/setup-uv@v7`, and
`hashicorp/setup-terraform@v3` in `.github/workflows/ci.yml:23`. Container bases
are pinned by version tag rather than digest, and no Dependabot or equivalent
update configuration is present.

**Reproduction:** Inspect workflow `uses:` entries, Dockerfile `FROM` entries,
and `.github` dependency-update configuration.

**Risk:** A compromised or unexpectedly changed upstream tag can alter trusted
build behavior without a repository diff. Manual-only updates also increase the
chance of stale dependencies.

### F-09 — Improvement: LocalStack Terraform verification silently skips

**Issue:** [#53 — Provision an AWS environment with Terraform](https://github.com/ramioooz/agreement-intelligence/issues/53)

**Evidence:** `tests/infra/test-terraform-contract.sh:16` prints a warning and
returns success when `tflocal` is absent. The review therefore validated
Terraform syntax but did not create or assert emulated resources. Detailed
review evidence is attached to #53.

**Reproduction:** Run `make terraform-check` on a machine with Terraform but
without `tflocal`.

**Risk:** CI can report successful local-cloud verification even though its
provider endpoint and resource contracts were never exercised.

## Boundaries reviewed with no new finding

| Boundary | Review conclusion |
| --- | --- |
| Authentication and logout | NextAuth uses OIDC state and PKCE, HTTP-only SameSite cookies, secure production cookies, token refresh, controlled Keycloak logout, and fail-closed API token validation. |
| Application authorization | API routes consistently combine permissions with organization/workspace checks and hide unauthorized resources. Reviewer, approver, administrator, and viewer responsibilities remain separated. |
| Object storage access | Keys are organization/workspace scoped, writes are immutable, and download paths validate scoped prefixes. F-02 concerns completeness and transaction ordering of deletion, not ordinary reads. |
| Agreement version lineage | Version rows are checksum-addressed and immutable with optimistic current-version checks and idempotency. |
| Worker delivery | SQS messages are acknowledged only after successful handling; exceptions preserve redelivery, and artifact writes are idempotent. F-05 concerns initial outbox publication recovery. |
| Model-provider fallback | Provider failures retain deterministic results and safe provenance; provider output cannot silently replace deterministic authority. |
| Citation integrity and prompt injection | Recent guardrail work validates evidence anchors, preserves exact semantics, rejects ungrounded claims, and treats document text as untrusted evidence. Focused suites and the full source suite passed. |
| Grounded Q&A history | Each turn performs fresh scoped retrieval, inaccessible historical evidence is removed, and unsupported answers fail explicitly. |
| MCP | The service is read-only, validates OIDC tokens fail closed, reuses API tenant/permission boundaries, and records scoped audit/trace metadata. |
| Local network exposure | Compose-published services bind to loopback by default; application containers run with reduced privileges where configured. Internet-facing controls remain cloud-deferred. |
| Dependencies and repository secrets | Locked production dependency audits and the full-history Gitleaks scan found no known vulnerability or committed secret. |
| Browser failure handling | Primary repository, processing, search, comparison, playbook, and review workflows expose actionable states. Further UX polish remains tracked by the release documentation/demo work rather than a security defect. |

## Deferred real-AWS validation

These items cannot be proven by LocalStack or the local Docker topology and
remain explicitly deferred:

- [#200 — Epic: Deferred AWS deployment and cloud validation](https://github.com/ramioooz/agreement-intelligence/issues/200)
- [#203 — Deploy and validate the application in real AWS](https://github.com/ramioooz/agreement-intelligence/issues/203)
- [#204 — Validate production cloud security, resilience, and operations](https://github.com/ramioooz/agreement-intelligence/issues/204)

They cover real IAM evaluation, VPC and security-group behavior, managed TLS,
load balancing, WAF, ECS/RDS behavior, Secrets Manager integration, backup and
restore, scaling, alarms, and destructive recovery exercises. Passing local
checks is useful parity evidence but is not presented as proof of these cloud
boundaries.

## Release recommendation

Do not make the repository public until F-01 through F-04 are fixed in dedicated
PRs and independently re-reviewed. Resolve F-05 through F-07 before describing
the locally demonstrable product as production-grade. F-08 and F-09 should be
closed as part of the Production Release hardening backlog. Real-AWS-only work
can remain deferred as long as the README and release documentation clearly
state that limitation.

[Back to contents](#contents)
