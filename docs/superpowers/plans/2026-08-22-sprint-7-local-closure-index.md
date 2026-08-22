# Sprint 7 Local Quality Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete every locally verifiable release, security, AI-quality, operations, and public-documentation requirement while moving genuine AWS validation into a non-blocking deferred backlog.

**Architecture:** Preserve the modular monorepo and extend the existing API, worker, web, MCP, PostgreSQL/pgvector, Redis, SQS/LocalStack, Terraform, and OpenTelemetry boundaries. Deliver independent issue-backed PRs in dependency waves, then prove the merged result from a fresh clone.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/Alembic, PostgreSQL/pgvector, Redis, SQS/S3 through LocalStack, TypeScript, Next.js, Playwright, OpenTelemetry, Terraform, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-22-local-public-release-design.md`

## Global Constraints

- Every source or documentation change starts with a GitHub issue attached beneath the correct epic.
- Every implementation uses a dedicated branch and `.worktrees/<task>` worktree.
- Every PR targets `main`, is ready for review, and is merged only by the repository owner.
- Branches, commits, and PR metadata do not contain assistant or provider branding.
- Use synthetic or legally reusable documents only.
- Do not commit credentials, model weights, access tokens, real agreements, or personal test data.
- Do not add LangChain, CrewAI, another message broker, or another vector database.
- PostgreSQL remains authoritative for durable state; Redis remains ephemeral coordination; SQS remains the durable job wake-up mechanism.
- LocalStack verification is not represented as proof of real AWS behavior.
- Repository visibility remains private until the owner completes manual QA and changes it explicitly.

---

## Plan set

Execute the focused plans in this order:

1. `2026-08-22-release-blockers.md`
   - dependency remediation;
   - privacy-safe data handling (#48);
   - prompt-injection and unsafe-output hardening (#49);
   - independent code/security review and issue creation for findings.
2. `2026-08-22-local-ai-platform-quality.md`
   - immutable AI configuration (#45);
   - unified evaluation gate (#46);
   - safe end-to-end observability (#47);
   - tenant quotas, rate limits, and budgets (#50).
3. `2026-08-22-local-operational-readiness.md`
   - performance and recovery (#51);
   - local backup, restore, and runbooks (#52);
   - Terraform and LocalStack validation (#53 local scope).
4. `2026-08-22-public-release-documentation.md`
   - license and community files;
   - README/navigation/architecture;
   - comprehensive manual QA and API testing;
   - clean-clone rehearsal and Sprint 7 closure (#55).

## Specification coverage

| Specification requirement | Implemented by |
| --- | --- |
| Local/cloud scope separation and tracking | This plan, Tasks 1–2 |
| Dependency and secret release blockers | `2026-08-22-release-blockers.md`, Tasks 1 and 4 |
| Privacy-safe telemetry and prompt-injection resistance | `2026-08-22-release-blockers.md`, Tasks 2–3 |
| Immutable AI configuration, evaluation, observability, and quotas | `2026-08-22-local-ai-platform-quality.md`, Tasks 1–4 |
| Performance, recovery, backup/restore, runbooks, and LocalStack Terraform | `2026-08-22-local-operational-readiness.md`, Tasks 1–5 |
| Native GitHub tabs and custom README navigation | `2026-08-22-public-release-documentation.md`, Tasks 1–2 |
| Provider-powered, no-key, and provider-outage behavior | `2026-08-22-public-release-documentation.md`, Tasks 2, 3, and 6 |
| Architecture diagrams and component/service communication | `2026-08-22-public-release-documentation.md`, Task 2 |
| Comprehensive manual QA and API/Insomnia testing | `2026-08-22-public-release-documentation.md`, Tasks 3–4 |
| Synthetic screenshots and clean-clone rehearsal | `2026-08-22-public-release-documentation.md`, Tasks 5–6 |
| Final automated gates, owner manual QA, and Project 6 closure | This plan, Task 4; `2026-08-22-public-release-documentation.md`, Task 7 |

## Dependency wave

```text
Tracking reconciliation
  ├─ dependency remediation ─┐
  ├─ privacy controls ───────┼─ code/security review fixes
  └─ injection hardening ────┘
              ↓
  AI config ──→ evaluation gate
      ├────────→ observability
      └────────→ quotas and budgets
              ↓
  performance/recovery ──→ backup/restore ──→ LocalStack/Terraform gate
              ↓
  README + architecture + manual QA + community files
              ↓
  fresh-clone automated gate ──→ owner manual QA ──→ project closure
```

### Task 1: Reconcile tracking before implementation

**Files:**
- Modify: GitHub issue #63 and its child relationships through the GitHub API
- Modify: GitHub issue #53 to retain only local Terraform/LocalStack acceptance in Project 6
- Modify: GitHub issue #52 to retain local backup/restore acceptance in Project 6
- Move: GitHub issue #54 to the deferred epic
- Move: GitHub issue #195 to the deferred epic

**Interfaces:**
- Consumes: approved scope in the specification
- Produces: one current local-release epic and one deferred cloud epic with no duplicate top-level Project items

- [ ] **Step 1: Create the deferred epic**

Create `EPIC: Deferred AWS Validation and Provider Recovery` with labels `type:epic`, `priority:p2`, and `area:infra`. Do not add it to GitHub Project 6.

- [ ] **Step 2: Move cloud-only stories**

Attach #54 and #195 beneath the deferred epic. Add child stories for real AWS apply/validation and managed-cloud disaster recovery; remove those acceptance statements from the current local stories without deleting history.

- [ ] **Step 3: Update Sprint 7 metadata**

Set #63 work mode to `Dependency-wave delivery`, add the dependency and code-review stories, and set the Project status to `In Progress`.

- [ ] **Step 4: Reconcile stale issue #144**

Verify its requested playbook behavior exists on `main`. If fully delivered, comment with the merged PR evidence and close it; otherwise attach it to #63 and schedule it in the release-blocker wave.

- [ ] **Step 5: Record the updated structure**

Capture the resulting epic/child hierarchy in the implementation PR description; do not add child stories as top-level Project items.

### Task 2: Create one issue per execution unit

**Files:**
- Modify: GitHub issue hierarchy beneath #63

**Interfaces:**
- Consumes: four focused plan documents
- Produces: reviewable issues for dependency remediation, code/security review, and any story split required by the plans

- [ ] **Step 1: Create the production-dependency issue**

Title it `STORY: Remediate production dependency vulnerabilities` and give it `priority:p0`, `area:security`, and `security-critical`.

- [ ] **Step 2: Create the independent review issue**

Title it `STORY: Complete the pre-publication code and security review` and give it `priority:p0`, `area:security`, and `area:docs`.

- [ ] **Step 3: Attach both issues beneath #63**

Do not add them independently to Project 6.

- [ ] **Step 4: Set child status only when work begins**

Keep pending children `Todo`; set one to `In Progress` when its branch/worktree is created; set it `Done` only after owner merge and verification evidence.

### Task 3: Execute the four focused plans

**Files:**
- Read: all four plan files listed in the Plan set

**Interfaces:**
- Consumes: merged output of each dependency wave
- Produces: owner-reviewed, independently testable PRs in the required order

- [ ] **Step 1: Execute release blockers**

Use `2026-08-22-release-blockers.md`. Stop the later waves if a release blocker remains open.

- [ ] **Step 2: Execute AI platform quality**

Use `2026-08-22-local-ai-platform-quality.md`. Merge #45 before #46/#47/#50 where they consume configuration versions.

- [ ] **Step 3: Execute operational readiness**

Use `2026-08-22-local-operational-readiness.md`. Preserve developer volumes unless a test explicitly uses disposable resources.

- [ ] **Step 4: Execute documentation and rehearsal**

Use `2026-08-22-public-release-documentation.md`. Documentation must describe the merged system, not branches under review.

### Task 4: Run the final merged release gate

**Files:**
- Modify: `docs/testing/release-evidence.md`
- Modify: GitHub issue #55
- Modify: GitHub issue #63

**Interfaces:**
- Consumes: merged code, infrastructure, documentation, and tests
- Produces: reproducible evidence for the owner’s final visibility decision

- [ ] **Step 1: Verify source and dependency quality**

Run:

```bash
make check
pnpm audit --prod --audit-level high
uv run pip-audit
make terraform-check
```

Expected: every command exits zero and no high/critical production vulnerability remains.

- [ ] **Step 2: Verify history and tenant isolation**

Run the full-history secret scanner and the disposable PostgreSQL RLS integration command documented by the release-blocker plan.

Expected: zero leaked secrets and zero unauthorized rows.

- [ ] **Step 3: Verify a fresh stack**

Run:

```bash
make stack-down
make stack-up
make stack-check
```

Expected: application services are healthy; bootstrap containers exit successfully.

- [ ] **Step 4: Run critical browser journeys**

Run the documented Playwright release project with one worker against the fresh stack.

Expected: authentication, repository, analysis, search/Q&A, comparison, playbook, review, approval, and package journeys pass.

- [ ] **Step 5: Record evidence**

Add commands, dates, exit results, environment versions, and links to synthetic screenshots to `docs/testing/release-evidence.md`. Never paste secrets, raw agreements, prompts, or provider output.

- [ ] **Step 6: Owner manual QA checkpoint**

The repository owner executes `docs/testing/manual-test-plan.md` and records Pass, Fail, or Blocked for every release-critical case. Failures become issue-backed fixes before closure.

- [ ] **Step 7: Close the local project**

After every release-critical case passes, update #55 and #63 checklists, mark their Project items `Done`, close #63, and clean merged worktrees and local/remote branches. Leave the deferred epic open outside Project 6 and leave repository visibility unchanged.
