# Public Documentation and Release Rehearsal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the private repository understandable, runnable, testable, and honestly assessable by a newcomer before the owner chooses public visibility.

**Architecture:** The README is the concise entry point; focused documents own architecture, manual QA, API testing, operations, security, and roadmap detail. GitHub-native community files provide repository tabs, while an inline README navigation row links the custom documentation areas.

**Tech Stack:** GitHub-flavored Markdown, Mermaid, Docker Compose, Make, Insomnia/OpenAPI, Playwright, synthetic screenshots, GitHub community health files.

**Spec:** `docs/superpowers/specs/2026-08-22-local-public-release-design.md`

## Global Constraints

- Documentation describes merged behavior only.
- Full product behavior requires a user-supplied provider key; no-key degradation is documented separately and tested.
- Screenshots, examples, and API collections use synthetic data only.
- Never place secrets in command lines, screenshots, Insomnia exports, logs, or evidence files.
- Do not claim real OCR, real AWS deployment validation, cloud federation, or automatic AI backfill.
- Use relative repository links and verify every internal link.
- Repository visibility remains private; changing visibility is an owner-only action outside the PR.

---

### Task 1: Add public community and policy files (#55)

**Files:**
- Create: `LICENSE`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Modify: `CONTRIBUTING.md`
- Create: `docs/security/threat-model.md`
- Create: `docs/security/responsible-ai.md`

**Interfaces:**
- Produces: GitHub-native README, Code of conduct, Contributing, Apache-2.0 license, and Security tabs
- Consumes: actual reporting boundaries, local security gates, and approved public-license decision

- [ ] **Step 1: Add the Apache License 2.0 text**

Use the unmodified official Apache License 2.0 text in `LICENSE` and use the repository owner name only where an optional copyright notice is needed outside the license text.

- [ ] **Step 2: Add the security policy**

Document supported release status, private vulnerability reporting, required report evidence, secret-handling expectations, response targets as goals rather than guarantees, and excluded public issue content.

- [ ] **Step 3: Add the code of conduct and contribution guide**

Use Contributor Covenant language and update `CONTRIBUTING.md` with issue-first delivery, branch/worktree rules, owner-only merge, toolchain setup, source checks, dependency audits, secret scans, synthetic-data rules, and documentation expectations.

- [ ] **Step 4: Add threat and responsible-AI documentation**

Cover assets, actors, trust boundaries, tenant isolation, untrusted documents, prompt injection, retrieval leakage, citations, human review, provider failure, PII, telemetry, MCP, residual risks, and deferred cloud validation.

- [ ] **Step 5: Verify**

```bash
pnpm exec prettier --check SECURITY.md CODE_OF_CONDUCT.md CONTRIBUTING.md docs/security
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add LICENSE SECURITY.md CODE_OF_CONDUCT.md CONTRIBUTING.md docs/security
git commit -m "docs: add public repository policies"
```

### Task 2: Rewrite the README and documentation index (#55)

**Files:**
- Modify: `README.md`
- Create: `docs/README.md`
- Create: `docs/getting-started.md`
- Create: `docs/roadmap.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/operations/platform-foundation.md`
- Create: `scripts/check-doc-links.mjs`
- Create: `tests/docs/test-documentation-contract.sh`

**Interfaces:**
- Produces: newcomer entry path and accurate links to every focused guide
- Consumes: merged application behavior, ports, roles, environment variables, Make targets, and deferred backlog

- [ ] **Step 1: Replace planned language with delivered behavior**

Remove stale claims that processing, search, comparison, playbooks, or approval are future work. Replace “OCR fallback” with the actual `ocr_required` diagnostic and explicitly state that an OCR engine/provider is not included.

- [ ] **Step 2: Add the custom navigation row**

Render this clickable row near the top, outside a code block:

```markdown
[Overview](#overview) | [Quick start](docs/getting-started.md) | [Architecture](docs/architecture/overview.md) | [Manual QA & API](docs/testing/manual-test-plan.md) | [Operations](docs/operations/platform-foundation.md) | [Roadmap](docs/roadmap.md)
```

Add a contents index and compact `[Back to contents](#contents)` links in long sections.

- [ ] **Step 3: Document prerequisites and fresh setup**

List pinned Node, pnpm, Python, uv, Docker Compose, Make, Terraform, and browser requirements. Explain copying `.env.example`, replacing placeholders, optional provider credentials, `make stack-up`, `make stack-check`, URLs, and non-destructive shutdown.

- [ ] **Step 4: Document operating modes**

Provide a capability matrix for full provider mode, no-key mode, and provider outage. Explain deterministic analysis, lexical retrieval, unavailable embeddings/answers, explicit failure states, query retry, current manual reprocessing, and deferred #195 backfill.

- [ ] **Step 5: Document roles and first walkthrough**

List platform administrator, legal reviewer, business approver, and any viewer/unauthorized test identities with permissions and password source. Walk through upload → analysis → playbook → search/Q&A → version comparison → review/approval → final package.

- [ ] **Step 6: Rewrite the architecture overview**

Add Mermaid diagrams for service communication, upload/queue/worker flow, hybrid retrieval/Q&A, version comparison, approval workflow, MCP tools, and telemetry redaction. Separate as-built local, cloud-valid reference, and deferred AWS validation.

- [ ] **Step 7: Add documentation index and roadmap**

`docs/README.md` describes every document’s audience and purpose. `docs/roadmap.md` lists provider adapters, OCR integration, automatic enrichment recovery #195, live AWS validation, federation, managed DR, and other honest improvements.

- [ ] **Step 8: Verify links and formatting**

Add `scripts/check-doc-links.mjs` and `tests/docs/test-documentation-contract.sh`. Validate relative file links, README anchors, required headings, prohibited stale claims, and required community files.

Run:

```bash
node scripts/check-doc-links.mjs
tests/docs/test-documentation-contract.sh
pnpm exec prettier --check README.md docs
git diff --check
```

- [ ] **Step 9: Commit**

```bash
git add README.md docs scripts/check-doc-links.mjs tests/docs/test-documentation-contract.sh
git commit -m "docs: rewrite the public project guide"
```

### Task 3: Create the comprehensive manual QA plan (#55)

**Files:**
- Create: `docs/testing/manual-test-plan.md`
- Create: `docs/testing/test-data.md`
- Create: `docs/testing/evidence-template.md`
- Create: `docs/testing/release-evidence.md`

**Interfaces:**
- Produces: stable `MQA-*` test cases with Pass/Fail/Blocked recording
- Consumes: seeded identities, synthetic agreements, browser routes, API contracts, operational scripts, and expected authorization behavior

- [ ] **Step 1: Define execution conventions**

Document environment reset rules, safe data, browser/Insomnia prerequisites, evidence naming, test status definitions, defect reporting, and which tests are destructive. Ordinary tests preserve local volumes.

- [ ] **Step 2: Write installation and identity cases**

Cover fresh setup, stack health, sign-in, silent Keycloak logout, role navigation, disabled/unauthorized user, session expiry, and tenant/workspace denial.

- [ ] **Step 3: Write repository and analysis cases**

Cover PDF/DOCX upload, immediate list refresh, viewer, permanent admin deletion/audit, version upload, duplicate rejection, processing/requeue, provider-powered analysis, no-key mode, OCR-required diagnostic, citations, and invalid file handling.

- [ ] **Step 4: Write intelligence cases**

Cover playbook create/edit/publish/archive/delete-draft/routing, search filters, lexical and semantic retrieval, grounded Q&A, insufficient/conflicting evidence, citation navigation, agreement version comparison, materiality, and unresolved alignment.

- [ ] **Step 5: Write approval and audit cases**

Cover policy creation, legal/business stage separation, assignments, comments, decisions, request changes, successor version, self-approval denial, notifications, audit timeline, PDF/JSON packages, checksums, reload persistence, and cross-workspace denial.

- [ ] **Step 6: Write integration and operations cases**

Cover MCP invalid/valid/cross-tenant calls, Insomnia APIs, stack restart/persistence, queue backlog, duplicate messages, worker restart, provider outage, local backup/restore, and safe troubleshooting.

- [ ] **Step 7: Write browser quality cases**

Cover supported desktop browsers, responsive widths, keyboard-only actions, visible focus, form labels, confirmation dialogs, actionable error pages, and refresh behavior.

- [ ] **Step 8: Verify completeness**

`tests/docs/test-documentation-contract.sh` must assert every required section exists and every test contains ID, purpose, identity, preconditions, steps, expected result, evidence, cleanup, and result field.

- [ ] **Step 9: Commit**

```bash
git add docs/testing
git commit -m "docs: add comprehensive manual QA plan"
```

### Task 4: Add safe API and Insomnia testing guidance (#55)

**Files:**
- Superseded: API instructions are now combined in `docs/testing/manual-test-plan.md`
- Create: `docs/testing/insomnia/agreement-intelligence.yaml`
- Modify: `tests/docs/test-documentation-contract.sh`

**Interfaces:**
- Produces: importable request collection with environment placeholders and no secret values
- Consumes: generated OpenAPI endpoints, local Keycloak token endpoint, organization/workspace scope, and seeded identities

- [ ] **Step 1: Define safe environments**

Use placeholders for base URLs, realm, client ID, username, password, organization ID, workspace ID, agreement ID, review ID, and bearer token. Mark exported cookies/tokens as private and excluded from commits.

- [ ] **Step 2: Add request groups**

Include health, identity/capabilities, agreements/documents, processing, versions/comparisons, playbooks/findings, search/Q&A, approval policies/reviews, audit, packages, and negative authorization requests.

- [ ] **Step 3: Add expected contracts**

For every request document method/path, required headers/query/body, expected success status, expected denial status, idempotency behavior, and cleanup.

- [ ] **Step 4: Validate the collection**

Add a script assertion that the YAML contains no bearer token, provider key, `change-me` secret, cookie, or real email and that all referenced local paths exist in the OpenAPI schema generated by the running API.

- [ ] **Step 5: Commit**

```bash
git add docs/testing/manual-test-plan.md docs/testing/insomnia tests/docs/test-documentation-contract.sh
git commit -m "docs: add safe API test collection"
```

### Task 5: Capture synthetic product screenshots (#55)

**Files:**
- Create: `docs/assets/dashboard.png`
- Create: `docs/assets/agreement-analysis.png`
- Create: `docs/assets/grounded-search.png`
- Create: `docs/assets/version-comparison.png`
- Create: `docs/assets/approval-workflow.png`
- Modify: `README.md`
- Modify: `docs/testing/manual-test-plan.md`

**Interfaces:**
- Consumes: fresh stack seeded only with synthetic agreements and demo identities
- Produces: compressed screenshots that illustrate current UI without exposing credentials or personal data

- [ ] **Step 1: Seed synthetic demonstration data**

Use the frozen legal fixtures or a newly authored synthetic client agreement with fictional names and no personal contact data.

- [ ] **Step 2: Capture critical states**

Use Playwright/browser automation at a consistent desktop viewport. Capture only completed, representative screens and crop browser chrome if it could reveal personal bookmarks or extensions.

- [ ] **Step 3: Inspect every image**

Verify no real name, email, local filesystem path, key, token, session ID, tenant secret, or confidential document text is visible.

- [ ] **Step 4: Link selectively**

Use the dashboard and one intelligence screenshot in README; link the remaining images from architecture/manual QA sections where they clarify expected state.

- [ ] **Step 5: Verify size and rendering**

Open every image and confirm readable text at GitHub width. Keep each image reasonably compressed and record alt text for accessibility.

- [ ] **Step 6: Commit**

```bash
git add docs/assets README.md docs/testing/manual-test-plan.md
git commit -m "docs: add synthetic product walkthrough images"
```

### Task 6: Run the clean-clone release rehearsal (#55)

**Files:**
- Create: `scripts/release-check.sh`
- Create: `apps/web/e2e/public-release.spec.ts`
- Modify: `Makefile`
- Modify: `apps/web/playwright.config.ts`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/ci/test-ci-workflow.sh`
- Modify: `docs/testing/release-evidence.md`

**Interfaces:**
- Produces: one command that executes non-provider release gates plus documented opt-in provider and browser checks
- Consumes: pinned toolchains, safe environment template, disposable database, LocalStack, and synthetic E2E data

- [ ] **Step 1: Implement the non-destructive release script**

`scripts/release-check.sh` verifies tool versions, placeholders, formatting/lint/types/tests/build, production dependency audits, secret scan availability, Terraform/LocalStack, documentation contracts, stack health, RLS isolation, deterministic AI evaluation, and critical E2E. It requires an explicit disposable test database URL for RLS and never invokes `stack-reset`.

- [ ] **Step 2: Add Make and CI contracts**

Add `make release-check` and assert the target exists. Add a Playwright `release` project whose `testMatch` is `public-release.spec.ts`, runs with one worker, retains traces/screenshots on failure, and exercises authentication, repository upload/analysis, search/Q&A, comparison, playbook review, approval, and package download using synthetic data. CI may split long-running container/browser checks into a dedicated job while retaining the same commands.

- [ ] **Step 3: Rehearse from a fresh clone**

Clone into a temporary directory, follow only README/getting-started instructions, create `.env` from the example, provide synthetic secrets, run setup and stack commands, and execute the release script.

- [ ] **Step 4: Verify provider modes separately**

First run without a provider key and record documented degraded behavior. Then add the owner’s ignored local key, run `make provider-smoke`, upload a synthetic agreement, verify embeddings/analysis/Q&A provenance, and remove the temporary clone afterward.

- [ ] **Step 5: Record evidence**

Add versions, commands, timestamps, exit results, evaluation report links, and synthetic screenshot links. Record secret scan as pass/fail without copying detected secret values.

- [ ] **Step 6: Owner manual test pass**

The owner executes every release-critical case in `manual-test-plan.md`. Each failure creates a GitHub issue and dedicated PR; the release remains private until blockers pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/release-check.sh Makefile apps/web/playwright.config.ts apps/web/e2e/public-release.spec.ts .github/workflows/ci.yml tests/ci/test-ci-workflow.sh docs/testing/release-evidence.md
git commit -m "test: add public release rehearsal"
```

### Task 7: Close Sprint 7 without changing visibility

**Files:**
- Modify: GitHub issues #45–#55 and #63
- Modify: GitHub Project 6 statuses

**Interfaces:**
- Consumes: merged PRs, automated evidence, owner manual QA results, and deferred epic
- Produces: completed local Project 6 with transparent deferred backlog

- [ ] **Step 1: Reconcile every checklist**

Check only acceptance criteria supported by merged evidence. Link each issue to its PR, commands, reports, and screenshots.

- [ ] **Step 2: Move cloud-only acceptance**

Confirm #54, #195, live AWS application, cloud DR, federation, and cloud cost/load verification remain under the deferred epic outside Project 6.

- [ ] **Step 3: Complete Project 6**

Mark all current local stories and #63 `Done`, close #63, and retain only parent sprint epics as top-level Project rows.

- [ ] **Step 4: Clean merged development state**

Remove merged `.worktrees/<task>` directories and merged local/remote feature branches after confirming clean status and ancestry.

- [ ] **Step 5: Leave visibility owner-controlled**

Report that the repository is ready for the owner’s visibility decision. Do not call any repository-visibility mutation.
