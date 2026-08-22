# Local Public Release and Quality Closure Design

## Goal

Prepare Agreement Intelligence for an owner-approved public release by completing and verifying all meaningful work that can run locally, documenting the product honestly, and separating work that genuinely requires a real AWS environment into a deferred backlog.

The release must be useful to two audiences equally:

- technical reviewers evaluating the architecture, security boundaries, AI engineering, and code quality;
- developers and QA testers cloning the repository to run and test the product themselves.

Repository visibility remains private until the owner completes the documented manual test plan and explicitly changes it.

## Release definition

The initial public release is a locally production-oriented demonstration, not a claim that the application has been validated in a live AWS environment. It must provide:

- a fully containerized local application;
- realistic agreement ingestion, analysis, retrieval, comparison, playbook, and approval workflows;
- a real provider-powered experience when the user supplies the required API credentials;
- explicit degraded behavior when provider credentials or service availability are absent;
- tenant-safe authorization and evidence handling;
- repeatable automated and manual verification;
- cloud-valid infrastructure and a clear migration path;
- honest limitations and deferred work.

## Scope boundary

### Complete and verify locally

The following Sprint 7 work remains in the current release scope:

- production dependency remediation and stronger dependency-audit gates;
- privacy-safe logs, telemetry, audit metadata, and retention guidance;
- prompt-injection and untrusted-document defenses;
- immutable prompt, model, schema, and AI-configuration governance;
- evaluation and regression gates;
- application-wide OpenTelemetry coverage and safe local observability;
- distributed rate limits, tenant quotas, local cost controls, and coordination;
- concurrency, retry, idempotency, and local failure-recovery verification;
- local PostgreSQL and object-storage backup and restore procedures;
- Terraform formatting, validation, policy/security checks, and LocalStack provisioning tests;
- code, security, architecture, and documentation review;
- public-facing repository documentation and a comprehensive manual QA guide;
- a clean-clone release rehearsal.

Issue #53 is split by execution environment: Terraform and LocalStack verification remain current work, while real AWS application and validation are deferred. Issue #52 similarly retains local backup and restore now while cloud disaster-recovery exercises are deferred.

### Defer until a real AWS environment is authorized

A separate deferred epic outside GitHub Project 6 will track:

- owner-controlled Terraform `apply` in a real AWS account;
- ECS, RDS, ALB, WAF, IAM, networking, DNS, certificates, and autoscaling validation;
- production cloud cost and traffic testing;
- managed-service backup and disaster-recovery exercises;
- Cognito and Microsoft Entra federation;
- cloud security posture and operational readiness checks;
- provider-recovery reconciliation and historical AI-enrichment backfill from #195.

LocalStack is a high-value AWS-compatible emulator for local development and infrastructure tests. Passing LocalStack tests does not prove behavior of real AWS networking, IAM, managed databases, load balancing, WAF, federation, scaling, or cost controls.

## Delivery strategy

Implementation is delivered in four dependency-aware waves.

### Wave 1 — Public-release blockers

- Remediate high and critical production dependency vulnerabilities.
- Complete privacy-safe logging, retention, and telemetry controls from #48.
- Complete prompt-injection and evidence-boundary hardening from #49.
- Fix any release-blocking code-review findings.

### Wave 2 — Local AI platform quality

- Complete AI configuration governance from #45.
- Complete the unified evaluation and regression gate from #46.
- Complete safe OpenTelemetry and local observability from #47.
- Complete tenant-aware quotas, rate limits, and local cost controls from #50.

### Wave 3 — Local operational readiness

- Complete performance, concurrency, and failure recovery from #51.
- Complete local backup, restore, and operational runbooks from #52.
- Complete Terraform and LocalStack verification from the local portion of #53.

### Wave 4 — Public-release documentation and rehearsal

- Complete public-release story #55.
- Add the Apache License 2.0 license.
- Rewrite the main README and documentation index.
- Update architecture, operations, security, and responsible-AI documentation.
- Add comprehensive manual browser and API test instructions.
- Add synthetic screenshots for important product journeys.
- Run the final fresh-clone rehearsal and owner-led manual QA pass.

Each independently reviewable change has a GitHub issue, dedicated branch, `.worktrees/<task>` worktree, focused verification, and a ready pull request targeting `main`. Only the repository owner merges. Merged worktrees and local/remote feature branches are removed promptly.

## Documentation information architecture

### Native GitHub repository tabs

GitHub will expose its native repository-overview tabs through recognized community files:

- `README.md` → README
- `CODE_OF_CONDUCT.md` → Code of conduct
- `CONTRIBUTING.md` → Contributing
- `LICENSE` → Apache-2.0 license
- `SECURITY.md` → Security

These are GitHub-managed tabs. Custom repository tabs such as Architecture or Manual QA cannot be added to that native bar.

### Custom README navigation

The README will include a prominent clickable navigation row near the top:

```text
Overview | Quick start | Architecture | Manual QA | API testing | Operations | Roadmap
```

The rendered row will use ordinary Markdown links, not a code block. Links may target README anchors or dedicated documents. The README will also contain:

- a contents index;
- stable heading anchors;
- relative links among related documents;
- small “Back to contents” links in long sections;
- a documentation index that describes the purpose of each document;
- collapsible `<details>` blocks only for optional detail that would otherwise interrupt the primary path.

### README structure

The public README will contain:

1. Product purpose and business problem.
2. Delivered capabilities and selected synthetic screenshots.
3. Known limitations and deferred capabilities.
4. Technology stack and repository structure.
5. Prerequisites and supported local toolchain.
6. Quick start from a fresh clone.
7. Environment configuration.
8. Provider-powered and no-key operating modes.
9. Seeded identities, roles, and permissions.
10. First end-to-end product walkthrough.
11. As-built component and data-flow diagrams.
12. Containers, ports, storage, queues, and health checks.
13. Development, linting, testing, and troubleshooting.
14. Security, privacy, responsible AI, and data-handling boundaries.
15. LocalStack-to-AWS migration path.
16. Documentation index, roadmap, and contribution guidance.

The README must describe actual current behavior. It must not claim that a real OCR engine, live AWS deployment, cloud federation, or automatic provider-recovery backfill exists when only a boundary, diagnostic, emulator, or roadmap item is present.

## Operating modes and graceful degradation

### Provider-powered mode

For the complete product experience, a user supplies the configured provider API key and model settings. Provider-backed functionality includes document enrichment, embeddings, semantic retrieval, grounded answer generation, and other model-assisted analysis exposed by the product.

The key remains local and uncommitted. Documentation will show how to configure it without printing it in logs, screenshots, commands, telemetry, test evidence, or pull requests.

### No-key or provider-unavailable mode

The application must start without provider credentials and present its reduced capabilities clearly:

- deterministic parsing and rule logic continue where supported;
- keyword-based PostgreSQL lexical search remains available;
- semantic embeddings and provider-generated answers are unavailable or explicitly degraded;
- the UI and API return actionable status instead of pretending that provider-backed output exists;
- repository browsing and unrelated business workflows remain accessible.

Lexical search matches normalized query terms against indexed document text and ranks textual matches. It exists both as part of hybrid retrieval and as a resilience fallback; it is not presented as equivalent to semantic retrieval.

New search queries retry query embedding when the provider is available again. Document embedding and analysis jobs retain explicit failure or unavailable state, but guaranteed automatic historical reconciliation is deferred to #195. The README and operations guide will explain the current manual recovery path and the planned backfill capability.

## Architecture documentation

Architecture documentation will distinguish three views:

1. **As-built local system** — web, API, worker, MCP service, PostgreSQL/pgvector, Redis, Keycloak, LocalStack S3/SQS, OpenTelemetry Collector, and local observability components.
2. **Cloud-valid reference** — the intended AWS mappings and Terraform boundaries without claiming deployment proof.
3. **Deferred live-cloud validation** — services and behaviors that require an actual AWS environment.

The diagrams will show at minimum:

- browser authentication and API authorization flow;
- upload, object storage, outbox, queue, worker, and artifact flow;
- deterministic and provider-assisted document-analysis paths;
- chunking, embeddings, pgvector, lexical search, result fusion, and cited Q&A;
- immutable agreement versions and comparisons;
- playbook routing, findings, review, approval, notifications, and final packages;
- MCP authentication, authorization, audit, and read-only tools;
- telemetry flow with the redaction boundary.

Diagrams use Mermaid where GitHub renders it reliably. Screenshots use only synthetic or legally reusable data.

## Manual QA documentation

The main manual plan will live at `docs/testing/manual-test-plan.md`. It is designed so a QA tester without undocumented project knowledge can execute the product end to end.

Every test case contains:

- stable test ID and title;
- purpose and risk covered;
- required identity and role;
- prerequisites and synthetic test data;
- exact browser or API-client steps;
- request method, path, headers, and expected status where applicable;
- visible and persisted expected results;
- evidence to capture;
- cleanup instructions;
- Pass, Fail, or Blocked result field.

The guide covers:

1. Fresh installation, configuration, health, and service discovery.
2. Authentication, single sign-out, seeded identities, and role boundaries.
3. Tenant and workspace isolation.
4. Agreement upload, view, delete, processing, versions, and reprocessing.
5. Provider-powered analysis and no-key degraded behavior.
6. Legal playbook creation, routing, versioning, publication, archive, and rule management.
7. Hybrid search, filters, Q&A, refusals, citations, and evidence navigation.
8. Version comparison, alignment, materiality, and uncertainty.
9. Review and multi-stage approval workflows.
10. Audit history, notifications, and immutable final packages.
11. Read-only MCP tools and their authorization boundary.
12. Insomnia-based API testing.
13. Restart, queue, retry, idempotency, and provider-outage behavior.
14. Local database and object-storage backup and restore.
15. Negative authorization, prompt-injection, PII, and secret-handling cases.
16. Browser compatibility, responsive layout, keyboard navigation, and basic accessibility.
17. Final public-release regression checklist.

Screenshots are included only when they materially clarify a route, control, or expected state. They never contain real agreements, personal accounts, access tokens, or provider credentials.

## Code-review scope

Before public release, an independent review covers:

- OIDC authentication, logout, role mapping, authorization, and tenant isolation;
- agreement storage, permanent deletion, immutable versions, and audit integrity;
- queue processing, outbox behavior, retries, idempotency, and recovery;
- retrieval grounding, citation validation, prompt injection, and untrusted documents;
- PII handling, telemetry redaction, secrets, and retention;
- migrations, row-level security, and cross-workspace access;
- dependency vulnerabilities and unsafe defaults;
- UI error states, accessibility, and incomplete journeys;
- accuracy of documentation against the implemented system.

Every finding is classified as:

- **Release blocker** — must be fixed before public visibility.
- **High priority** — should be fixed locally before project closure.
- **Improvement** — tracked and documented without blocking the initial release.
- **Cloud deferred** — requires real AWS deployment or external coordination.

No code is changed for an untracked finding. A new issue is created first and attached to the appropriate current or deferred epic.

## Public-release gates

The repository is ready for owner approval only when:

1. `make check` passes.
2. JavaScript and Python dependency audits contain no unresolved high or critical production vulnerability.
3. The full Git history passes secret scanning.
4. Row-level-security integration tests pass against a disposable PostgreSQL database.
5. Terraform formatting, validation, policy/security, and LocalStack checks pass.
6. A fresh clone starts using only the documented prerequisites and configuration.
7. `make stack-up` and `make stack-check` pass.
8. Critical Playwright journeys pass against the fresh stack.
9. The manual QA guide is executable without undocumented knowledge.
10. Documentation clearly distinguishes implemented local behavior, optional provider behavior, deterministic fallback, the cloud-valid reference, and deferred AWS validation.
11. Logs, telemetry, screenshots, fixtures, reports, and repository history contain no credentials or confidential agreement data.

Automated and browser evidence is attached to the relevant issue and pull request. Provider latency, quality, and cost may be reported without becoming flaky release gates unless a frozen deterministic threshold exists.

## Failure handling and troubleshooting

The public documentation will provide actionable diagnosis for:

- missing `.env` or placeholder configuration;
- missing or invalid provider credentials;
- unavailable provider or embedding service;
- unhealthy Keycloak or bootstrap job;
- unavailable LocalStack resources or incorrect queue configuration;
- worker jobs stuck in queued, processing, or failed state;
- database migration and row-level-security test setup;
- stale browser authentication sessions;
- missing Terraform or other local prerequisites;
- port conflicts and unsupported tool versions;
- restoring the local data services after a documented reset.

Troubleshooting favors non-destructive inspection. Any reset command is clearly marked as destructive and separated from ordinary startup instructions.

## Tracking and closure

The Sprint 7 epic remains the parent of all current local completion work. Only parent sprint epics remain top-level items in GitHub Project 6; stories remain nested children.

Before closure:

- stale or already-delivered issues are reconciled rather than left misleadingly open;
- AWS-only work moves to the separate deferred epic outside Project 6;
- every current story has verification evidence and an owner-merged pull request;
- the owner executes the manual QA plan and reports failures;
- release blockers are fixed through issue-backed pull requests;
- merged branches and worktrees are cleaned locally and remotely.

After the local gates pass, Sprint 7 and Project 6 may be marked complete. Deferred AWS and provider-recovery work remains visible but does not block local project closure. The repository stays private until the owner explicitly makes it public.

## Non-goals

- Claiming that LocalStack proves production AWS behavior.
- Deploying or applying infrastructure in an AWS account without owner authorization.
- Adding another message broker, vector database, orchestration framework, or AI framework solely for portfolio visibility.
- Implementing Cognito or enterprise identity federation for the local release.
- Implementing provider-recovery backfill in this release.
- Committing model weights, provider credentials, real agreements, or confidential test data.
- Changing repository visibility automatically.

## Approved decisions

- Local completion and public documentation are equally important.
- Apache License 2.0 is the intended public license.
- A provider API key is required for the full real-world experience, while no-key behavior remains documented and usable in degraded mode.
- The README uses both GitHub-native community tabs and a custom clickable navigation row.
- Manual QA documentation is comprehensive and intended for the repository owner’s pre-publication test pass.
- Only work requiring real AWS validation is deferred; locally implementable security, quality, operations, and documentation work remains in scope.
