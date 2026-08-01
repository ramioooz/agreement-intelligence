# Sprint 3 — Playbook Risk Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver versioned, policy-governed legal playbook review from administrator setup through cited reviewer decision and export.

**Architecture:** The API persists tenant-scoped immutable policy versions, evaluation findings, and append-only decisions. The worker evaluates completed agreement-analysis artifacts under those policy constraints. Next.js reads those persisted contracts for administration and clause-centric review; it never derives policy from model prose.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, Python worker, OpenAI-compatible structured analysis, Next.js 16, React 19, Vitest, Playwright, Docker Compose.

## Global Constraints

- Every branch and PR maps to its GitHub story: #21 through #27; the repository owner alone merges to `main`.
- All new data is organization/workspace scoped and access is checked by the API, not browser role claims.
- Only `platform_admin` has `playbooks:manage`; `legal_reviewer` can decide findings but cannot mutate policy.
- Published playbook versions and reviewer decision events are immutable.
- Policy severity and approved fallback language are authoritative; model output cannot override or invent them.
- Add only critical regression tests plus Playwright coverage for UI stories; run `make check` for every PR.

## File ownership and dependency map

| Story | Primary files | Depends on |
| --- | --- | --- |
| #21 | `apps/api/.../playbooks/{models,schemas,service,routes}.py`, migration | none |
| #22 | `apps/web/src/app/dashboard/playbooks/**`, `apps/web/src/components/playbook-*.tsx` | #21 |
| #23 | `apps/worker/.../playbook_evaluation.py`, `apps/api/.../reviews/**` | #21 |
| #24 | `apps/worker/.../risk_explanation.py` | #23 |
| #25 | `apps/worker/.../fallback_suggestions.py` | #23, #24 |
| #26 | `apps/web/src/app/dashboard/agreements/[agreementId]/review/page.tsx`, `review-workspace.tsx` | #23–#25 |
| #27 | `apps/api/.../reviews/decisions.py`, export route, `review-decisions.tsx` | #23–#26 |

### Task 1: #21 — Persist and publish legal playbooks

**Files:**
- Create: `apps/api/src/agreement_intelligence_api/playbooks/models.py`, `schemas.py`, `service.py`, `routes.py`, `__init__.py`.
- Create: `apps/api/migrations/versions/20260801_0008_legal_playbooks.py`.
- Modify: `apps/api/src/agreement_intelligence_api/main.py`, `apps/api/src/agreement_intelligence_api/identity/permissions.py`.
- Test: `apps/api/tests/test_playbooks.py`.

**Interfaces produced:**

```python
class PlaybookVersionResponse(BaseModel):
    id: UUID; playbook_id: UUID; version: int
    status: Literal["draft", "published"]
    agreement_family: str; rules: list[PlaybookRuleResponse]

POST /playbooks -> PlaybookVersionResponse
POST /playbooks/{playbook_id}/versions/{version}/publish -> PlaybookVersionResponse
GET /playbooks?organization_id=&workspace_id=&agreement_family= -> list[PlaybookVersionResponse]
```

- [ ] Write tests proving a platform administrator can create a draft; `legal_admin` and `legal_reviewer` receive forbidden access; a published version rejects rule mutation; publication rejects duplicate clause types and missing required policy content.
- [ ] Run `uv run pytest apps/api/tests/test_playbooks.py -v` and confirm the routes/models do not yet exist.
- [ ] Add `LegalPlaybookRecord`, `PlaybookVersionRecord`, and `PlaybookRuleRecord`, each with organization/workspace foreign keys; enforce unique `(playbook_id, version)` and `(playbook_version_id, clause_type)`.
- [ ] Add migration `0008` with the tables, indexes on tenant scope/status, and immutable-published service validation.
- [ ] Implement scoped service methods and routes. Remove `PLAYBOOKS_MANAGE` from `LEGAL_ADMIN`; retain it only via `PLATFORM_ADMIN: frozenset(PermissionKey)`.
- [ ] Append audit events for draft creation, rule updates, publication, and draft deletion; require explicit request confirmation for deletion.
- [ ] Re-run the focused test and `make check`; commit `feat: add versioned legal playbooks`.

### Task 2: #22 — Playbook administration experience

**Files:**
- Create: `apps/web/src/app/dashboard/playbooks/page.tsx`, `apps/web/src/app/dashboard/playbooks/[playbookId]/page.tsx`, `apps/web/src/components/playbook-editor.tsx`, `apps/web/src/components/playbook-version-list.tsx`, `apps/web/src/lib/playbook-api.ts`.
- Modify: `apps/web/src/components/dashboard-shell.tsx`.
- Test: `apps/web/src/components/playbook-editor.test.tsx`, `apps/web/e2e/playbook-admin.spec.ts` and Playwright configuration/scripts.

**Consumes:** Task 1 response shapes and `POST /playbooks/{id}/versions/{version}/publish`.

- [ ] Write a component test that platform-admin controls render a draft rule form and that publication is disabled until required fields are present.
- [ ] Add a Playwright scenario: sign in as admin, create a Client Agreement draft, add a limitation-of-liability rule, publish it, and see its immutable Published badge.
- [ ] Implement typed API functions, server actions, accessible validation messages, destructive confirmation, version list, and dashboard navigation.
- [ ] Use application capability data to hide mutation controls for non-admins; retain API enforcement from Task 1.
- [ ] Run the component test, `pnpm --filter @agreement-intelligence/web test`, `make stack-up`, and the Playwright scenario; commit `feat: add playbook administration`.

### Task 3: #23 — Evaluate agreements against a published playbook

**Files:**
- Create: `apps/api/src/agreement_intelligence_api/reviews/models.py`, `schemas.py`, `service.py`, `routes.py`, `__init__.py`.
- Create: `apps/api/migrations/versions/20260801_0009_playbook_evaluations.py`.
- Create: `apps/worker/src/agreement_intelligence_worker/playbook_evaluation.py`.
- Modify: `apps/worker/src/agreement_intelligence_worker/document_processor.py`, `apps/api/src/agreement_intelligence_api/main.py`.
- Test: `apps/worker/tests/test_playbook_evaluation.py`, `apps/api/tests/test_review_evaluations.py`.

**Interfaces produced:**

```python
class FindingResult(StrEnum):
    SATISFIED = "satisfied"; MISSING = "missing"
    NON_COMPLIANT = "non_compliant"; NEEDS_REVIEW = "needs_review"

class PlaybookFindingResponse(BaseModel):
    id: UUID; rule_id: UUID; result: FindingResult
    severity: str; confidence: float; method: Literal["deterministic", "semantic"]
    citation_ids: list[str]; playbook_version_id: UUID; extraction_version: str
```

- [ ] Write fixtures and tests for required clause satisfied, required clause missing, prohibited language non-compliant, and ambiguous evidence needing review.
- [ ] Add scoped evaluation/finding tables holding playbook version, extraction/analysis versions, cited evidence, result, confidence, method, and review state.
- [ ] Implement deterministic evaluation first: match extracted normalized clause type/source text against policy rules; return `needs_review` for absent or low-confidence evidence rather than compliant.
- [ ] Permit bounded semantic assessment only for explicitly configured rules; persist method and evidence for each output.
- [ ] Extend worker processing to run evaluation only after a completed agreement analysis and a selected published same-family playbook.
- [ ] Expose scoped evaluation/finding reads and review-run submission; run focused tests and `make check`; commit `feat: evaluate agreements against playbooks`.

### Task 4: #24 — Explain deviations and calibrate risk

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/risk_explanation.py`.
- Modify: `apps/worker/src/agreement_intelligence_worker/playbook_evaluation.py`, `apps/api/src/agreement_intelligence_api/reviews/{models,schemas,service}.py`.
- Test: `apps/worker/tests/test_risk_explanation.py`.

**Consumes:** `PlaybookFindingResponse`; **produces** `risk_rationale`, `risk_confidence`, and `review_status` stored on a finding.

- [ ] Write tests for compliant, non-compliant, ambiguous, and missing clause fixtures, including an assertion that an LLM explanation cannot change policy severity.
- [ ] Introduce a versioned risk payload with severity copied from the rule, cited rationale, confidence, and explicit review status.
- [ ] Generate an optional model explanation only from the rule, cited clause text, and deterministic result; reject ungrounded citation IDs.
- [ ] Persist the payload and expose it in finding reads; run focused test and `make check`; commit `feat: explain playbook risk findings`.

### Task 5: #25 — Produce approved fallback suggestions

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/fallback_suggestions.py`.
- Modify: `apps/worker/src/agreement_intelligence_worker/risk_explanation.py`, `apps/api/src/agreement_intelligence_api/reviews/{models,schemas}.py`.
- Test: `apps/worker/tests/test_fallback_suggestions.py`.

**Consumes:** persisted non-compliant/missing finding and the exact rule `preferred_language`/`fallback_language`.

- [ ] Write one test that emits an AI-generated, cited suggestion from approved fallback language and one that emits only a review recommendation where no approved language exists.
- [ ] Build suggestions solely by selecting approved position text and optionally asking the model to explain the comparison; never ask it to author policy prose.
- [ ] Store rule/version identifiers and a visible `ai_generated` flag with every suggestion.
- [ ] Run focused test and `make check`; commit `feat: add playbook fallback suggestions`.

### Task 6: #26 — Build the clause-centric reviewer workspace

**Files:**
- Create: `apps/web/src/app/dashboard/agreements/[agreementId]/review/page.tsx`, `apps/web/src/components/review-workspace.tsx`, `apps/web/src/components/review-finding-list.tsx`, `apps/web/src/lib/review-api.ts`.
- Modify: `apps/web/src/components/agreement-detail.tsx`.
- Test: `apps/web/src/components/review-workspace.test.tsx`, `apps/web/e2e/review-workspace.spec.ts`.

**Consumes:** `PlaybookFindingResponse` with citations, risk payload, and suggestion fields.

- [ ] Write a component test that selecting a high-risk finding updates its source-evidence panel and a low-confidence finding remains explicitly marked for human review.
- [ ] Add Playwright coverage that opens an analysed agreement, filters to high severity, selects a finding, verifies its citation/source location, and navigates by keyboard.
- [ ] Implement accessible outline, source viewer link/highlight target, finding list, severity/status filters, synchronized selected finding state, and loading/empty/failure states.
- [ ] Clearly label generated suggestions and render policy rationale separately from model explanation.
- [ ] Run the component test, stack, Playwright scenario, and `make check`; commit `feat: add legal review workspace`.

### Task 7: #27 — Record reviewer decisions and export review report

**Files:**
- Create: `apps/api/src/agreement_intelligence_api/reviews/decisions.py`, `export.py`.
- Create: `apps/api/migrations/versions/20260801_0010_review_decisions.py`.
- Create: `apps/web/src/components/review-decisions.tsx`, `apps/web/e2e/review-decision-export.spec.ts`.
- Modify: `apps/api/src/agreement_intelligence_api/reviews/{models,schemas,service,routes}.py`, `apps/web/src/components/review-workspace.tsx`.
- Test: `apps/api/tests/test_review_decisions.py`.

**Interfaces produced:**

```python
POST /review-findings/{finding_id}/decisions -> ReviewDecisionResponse
GET /agreements/{agreement_id}/review-report -> application/pdf
```

- [ ] Write tests that accepting then editing a finding preserves two immutable decision events and that report data includes agreement identity, playbook version, findings, decisions, and citation IDs.
- [ ] Add append-only `ReviewDecisionRecord`; reject update/delete operations and reconstruct current state from ordered event history.
- [ ] Enforce `REVIEWS_DECIDE` for legal reviewers and platform administrators; audit every decision and export.
- [ ] Implement an export service producing a cited PDF review report under the authorized scope.
- [ ] Add the accessible decision controls and export action to the workspace.
- [ ] Run API test, `make stack-up`, Playwright decision/export journey, and `make check`; commit `feat: add reviewer decisions and export`.

## Integration and review gates

- [ ] Rebase each branch onto the user-merged predecessor before opening its ready PR; no PR targets a feature branch.
- [ ] For each ready PR, run `make check`, the story’s focused API/worker checks, and the story’s Playwright scenario when it changes UI.
- [ ] After #27 merges, run one end-to-end browser journey: admin publishes policy, completed agreement evaluates, reviewer filters a risk, reviews evidence, records a decision, and downloads the cited report.
- [ ] Update the Sprint 3 epic and all stories to Done only after that journey is successful and the owner has merged every approved PR.
