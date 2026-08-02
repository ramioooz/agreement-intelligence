# Playbook Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make playbook selection unambiguous and playbook administration safe, auditable, and usable.

**Architecture:** Published playbooks receive explicit immutable routing scope and priority. The worker selects one matching published base playbook deterministically and persists its version in the existing evaluation record. Drafts are deletable; published policies are archived so historical evaluations remain reproducible. The administrator UI exposes scope, lifecycle controls, and removes test-created data after browser tests.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, Python worker, Next.js, Playwright.

## Global Constraints

- Only `platform_admin` holds `playbooks:manage`.
- Published versions and prior evaluation/report evidence remain immutable.
- A routing decision must be deterministic; an LLM does not select policy.
- Keep tests limited to lifecycle, routing-conflict, and browser cleanup paths.

---

### Task 1: Add playbook lifecycle and routing data

**Files:**
- Modify: `apps/api/src/agreement_intelligence_api/playbooks/{models,schemas,service,routes}.py`
- Create: `apps/api/migrations/versions/20260802_0013_playbook_governance.py`
- Test: `apps/api/tests/test_playbooks.py`

- [ ] Write failing API tests for draft deletion, published archive, and rejection of duplicate published routing scope.
- [ ] Run `uv run pytest apps/api/tests/test_playbooks.py -v` and confirm the new assertions fail.
- [ ] Add routing direction, jurisdiction, priority, lifecycle archive state, confirmation/reason fields, audit records, and scoped archive/delete routes.
- [ ] Run the focused API test and commit the working backend.

### Task 2: Route one policy and pin provenance

**Files:**
- Modify: `apps/worker/src/agreement_intelligence_worker/playbook_evaluation.py`
- Test: `apps/worker/tests/test_playbook_evaluation_sink.py`

- [ ] Write a failing worker test that supplies multiple published policies and asserts the matching priority policy is the only evaluation persisted.
- [ ] Run the focused worker test and confirm it fails under the current all-match selection behavior.
- [ ] Implement deterministic selection by family, direction, jurisdiction, priority, and stable identifier; exclude archived policies.
- [ ] Run the focused worker test and commit the routing change.

### Task 3: Govern the administrator experience and test data

**Files:**
- Modify: `apps/web/src/{lib/playbook-api.ts,app/dashboard/playbooks/page.tsx,app/dashboard/playbooks/[playbookId]/page.tsx,components/playbook-version-list.tsx}`
- Modify: `apps/web/e2e/playbook-admin.spec.ts`
- Test: `apps/web/src/components/playbook-editor.test.tsx`

- [ ] Write a failing component/browser assertion for visible routing scope and lifecycle action.
- [ ] Run the focused web test and confirm it fails.
- [ ] Render routing conditions and active/archive/delete actions only for authorized administrators; add confirmation and reason handling.
- [ ] Ensure browser-created playbooks are deleted in test cleanup, including failure-safe cleanup.
- [ ] Run focused browser E2E and project checks; commit the UI.

### Task 4: Verify and hand off

- [ ] Run backend, worker, web, formatting/type, and live browser checks appropriate to changed files.
- [ ] Inspect `git diff --check`, commit remaining changes, push `feat/playbook-governance`, and open a ready PR linked to #142.
