# Manual QA and API guide

This is the public, repeatable acceptance guide for Agreement Intelligence. It replaces
the previous 48-case checklist and the separate API-testing page with **14 critical
end-to-end tests**. Use synthetic fixtures only.

[Test list](#critical-test-list) | [Setup](#setup) | [Insomnia](#insomnia-setup) | [Results](#verified-results) | [Run the tests](#run-the-tests) | [Evidence](#evidence-and-cleanup)

## Contents

- [Critical test list](#critical-test-list)
- [Setup](#setup)
- [Insomnia setup](#insomnia-setup)
- [Verified results](#verified-results)
- [Run the tests](#run-the-tests)
  - [01 — Fresh clone and stack health](#01-fresh-clone-and-stack-health)
  - [02 — Authentication, roles, and navigation](#02-authentication-roles-and-navigation)
  - [03 — Upload, viewer, and automatic refresh](#03-upload-viewer-and-automatic-refresh)
  - [04 — OpenAI analysis and provenance](#04-openai-analysis-and-provenance)
  - [05 — No-key mode and provider recovery](#05-no-key-mode-and-provider-recovery)
  - [06 — Tenant and authorization isolation](#06-tenant-and-authorization-isolation)
  - [07 — Playbook lifecycle and routing](#07-playbook-lifecycle-and-routing)
  - [08 — Search, grounded Q&A, and citations](#08-search-grounded-qa-and-citations)
  - [09 — Revision and version comparison](#09-revision-and-version-comparison)
  - [10 — Legal and business approval](#10-legal-and-business-approval)
  - [11 — Request changes and final packages](#11-request-changes-and-final-packages)
  - [12 — Permanent deletion and immutable audit](#12-permanent-deletion-and-immutable-audit)
  - [13 — Critical API workflow in Insomnia](#13-critical-api-workflow-in-insomnia)
  - [14 — Recovery, hostile input, privacy, and keyboard use](#14-recovery-hostile-input-privacy-and-keyboard-use)
- [Evidence and cleanup](#evidence-and-cleanup)

## Critical test list

| ID | Critical journey | Primary evidence |
| --- | --- | --- |
| 01 | Fresh clone, setup, stack startup, and health | Terminal |
| 02 | Login, logout, roles, permissions, and restricted navigation | Browser |
| 03 | PDF/DOCX upload, viewer, and automatic processing refresh | Browser |
| 04 | Real OpenAI analysis, citations, and model provenance | Browser + terminal |
| 05 | No-key operation and recovery after restoring the key | Browser + terminal |
| 06 | Cross-tenant and unauthorized protection | Browser + Insomnia |
| 07 | Playbook create, edit, publish, route, archive, and draft deletion | Browser |
| 08 | Search, grounded Q&A, citations, and refusal | Browser |
| 09 | Immutable revision and version comparison | Browser |
| 10 | Legal/business approval and self-approval denial | Browser |
| 11 | Request changes, successor review, and final PDF/JSON | Browser |
| 12 | Permanent deletion and immutable audit | Browser + terminal |
| 13 | API validation, idempotency, and async polling in Insomnia | Insomnia |
| 14 | Worker recovery, hostile input, privacy, and keyboard access | Terminal + browser |

[Back to contents](#contents)

## Setup

### Tools

- Docker Desktop/Engine with Docker Compose 2.24 or newer
- GNU Make, Node.js 22, pnpm 10, Python 3.13, and `uv`
- Chrome, Chromium, Firefox, or Safari
- Insomnia for test 13
- An OpenAI API key for test 04; all other tests can run without one

### Prepare the local stack

```bash
make setup
cp .env.example .env
chmod 600 .env
# Replace every change-me value. OPENAI_API_KEY may remain empty initially.
scripts/validate-stack-env.sh .env
make stack-up
make stack-check
node scripts/generate-synthetic-agreements.mjs
```

Generated files are under `artifacts/manual-qa/fixtures/` and are ignored by Git. Demo
scope and identity names are documented in [test data](test-data.md). Read passwords from
the ignored `.env`; never paste them into this guide, screenshots, command arguments, or
an exported Insomnia environment.

### Test record

Record these once for the whole run, not under every case:

| Field | Value |
| --- | --- |
| Date | UTC date |
| Commit | `git rev-parse HEAD` |
| Host | OS, architecture, Docker version |
| Provider | `openai`, `openai-compatible`, or `none`; never record a key |
| Result owner | Initials or local QA run identifier |

[Back to contents](#contents)

## Insomnia setup

Import [`agreement-intelligence.yaml`](insomnia/agreement-intelligence.yaml) and create a
private local sub-environment. Do not edit or export the checked-in base environment.

| Variable | Local value |
| --- | --- |
| `base_url` | `http://localhost:8000` |
| `authorize_url` | `http://localhost:8080/realms/agreement-intelligence/protocol/openid-connect/auth` |
| `token_url` | `http://localhost:8080/realms/agreement-intelligence/protocol/openid-connect/token` |
| `client_id` / `client_secret` | Ignored `.env` values |
| `organization_id` | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` |
| `workspace_id` | `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` |
| `request_run_id` | A new non-secret UUID per logical run |
| Resource IDs | Copy only from synthetic create/list responses |

Use OAuth 2.0 Authorization Code with PKCE S256 and scopes `openid profile email`.
Temporarily add Insomnia's exact callback URI to the local Keycloak web client; never use
a wildcard or enable password grants. Remove the callback and clear the private token after
testing.

Important response contracts:

| Operation | Expected contract |
| --- | --- |
| First document upload | `201` |
| Duplicate checksum in the same scope | `200` with `duplicate: true` |
| Invalid/unsupported upload | `422` |
| Processing or comparison submission | `202`; send `Idempotency-Key` |
| Repeat same logical idempotent request | Same accepted resource/outcome |
| Foreign or hidden resource | Opaque `404` or empty authorized result |
| Final package still being built | `503 final_package_pending`; wait `Retry-After: 3` |
| Missing/corrupt/transient package object | `503 final_package_unavailable` |

Swagger UI is at <http://localhost:8000/docs>; the machine contract is
<http://localhost:8000/openapi.json>.

[Back to contents](#contents)

## Verified results

The repository owner should replace this snapshot with a new dated run before a public
release. The snapshot contains synthetic data only.

| ID | Result on 2026-08-28 | Observed evidence |
| --- | --- | --- |
| 01 | **Pass** | `make check`, provider/no-key stack startup, and `make stack-check` passed. |
| 02 | **Pass** | Release browser run authenticated admin, legal reviewer, and business approver. |
| 03 | **Pass** | Release journey uploaded and processed synthetic agreements without manual reload. |
| 04 | **Pass** | Real `gpt-5.4-mini` smoke passed: 508 input, 232 output tokens, 3899 ms, validation passed. |
| 05 | **Pass** | No-key stack stayed healthy and all 5 release browser journeys passed; provider worked after restore. |
| 06 | **Pass** | Focused tenant/auth suite passed within the 104-test security run. |
| 07 | **Pass with note** | Playbook suite passed 2/2 on rerun; the first cold run timed out once after publish. |
| 08 | **Pass** | Scoped search/Q&A release journeys passed, including cited and unavailable boundaries. |
| 09 | **Pass** | Revision/comparison release journey passed with deterministic materiality evidence. |
| 10 | **Pass** | Two-stage legal/business approval and immutable package browser journey passed. |
| 11 | **Partial** | Request changes, Version 2, successor review, reload, and package checks passed; the old review page still renders `Open` while its workflow is `revision_requested`. |
| 12 | **Pass** | Durable deletion, LocalStack cleanup, authorization, and audit coverage passed in the 104-test run. |
| 13 | **Pass** | Collection/OpenAPI contract and representative release API flows passed. |
| 14 | **Partial** | Functional recovery/security passed; 5-second restart objective passed once at 4.771 s and missed at 6.234, 6.619, and 5.776 s. |

The 104-test focused run covered tenant isolation, review authorization, permanent deletion,
LocalStack cleanup, bounded parsing, hostile-evidence guardrails, and privacy redaction.
The no-key release run passed 5/5 browser journeys in 2.0 minutes. Results marked **Partial**
are deliberately not presented as release passes.

[Back to contents](#contents)

## Run the tests

### 01 — Fresh clone and stack health

**Steps**

1. Clone the tested commit into a new directory and follow only [Getting started](../getting-started.md).
2. Leave provider keys empty; run `make setup`, `make stack-up`, and `make stack-check`.
3. Open the web app, API readiness, Swagger UI, and Keycloak on their documented ports.

**Expected:** setup succeeds without a provider key; all nine services are healthy; the
home page reports `API connected`.

**Actual:** **Pass** — source checks and both provider/no-key stack health checks passed.

### 02 — Authentication, roles, and navigation

**Steps**

1. Sign in separately as `platform.admin`, `legal.reviewer`, and `business.approver`.
2. Compare Repository, Search, Reviews, Playbooks, and policy-administration navigation.
3. Sign out and revisit a protected route.

**Expected:** each identity sees only permitted actions; policy administration is admin-only;
sign-out returns protected routes to authentication.

**Actual:** **Pass** — all three identities completed their role-specific release journeys.

### 03 — Upload, viewer, and automatic refresh

**Steps**

1. Upload `client-agreement-v1.pdf` and `liquidity-provider-v1.docx` from Repository.
2. Open each agreement and view/download its original document.
3. Stay on the detail page while processing changes from queued to completed.

**Expected:** both formats are accepted, originals render/download, and analysis appears
without leaving and reopening the page.

**Actual:** **Pass** — the synthetic upload/processing journey completed and refreshed in place.

### 04 — OpenAI analysis and provenance

**Steps**

1. Put a valid key in ignored `.env`, set `MODEL_GATEWAY_MODE=openai`, and recreate API/worker.
2. Run `make provider-smoke STACK_ENV_FILE=.env`.
3. Process a synthetic agreement and inspect citations and provenance; never use a real document.

**Expected:** strict provider output validates, citations resolve to supplied anchors, and the
model/provider are visible without exposing prompts, keys, or unrestricted text.

**Actual:** **Pass** — `gpt-5.4-mini`, 508 input tokens, 232 output tokens, 3899 ms,
`validation_status=passed`.

### 05 — No-key mode and provider recovery

**Steps**

1. Clear all provider key/base/fallback values in an ignored environment and recreate API/worker.
2. Run stack health, upload/process, lexical search, and a Q&A request.
3. Restore the ordinary ignored environment, recreate API/worker, and rerun provider smoke.

**Expected:** deterministic analysis, workflows, and lexical search remain available; Q&A
reports model unavailable rather than fabricating an answer; provider calls work after restore.

**Actual:** **Pass** — stack health plus 5/5 no-key browser journeys passed; provider smoke
passed after restoration.

### 06 — Tenant and authorization isolation

**Steps**

1. Create the fixed second-tenant fixture using `scripts/manual-qa-state.sh second-tenant-setup`.
2. As each demo identity, request its foreign agreement, citation, review, package, and search scope.
3. Repeat one allowed same-workspace request, then run `second-tenant-cleanup`.

**Expected:** foreign resources are hidden or absent; same-workspace authorized requests work;
cleanup removes only the fixed synthetic fixture.

**Actual:** **Pass** — cross-tenant agreement/review/package paths and RLS boundaries passed
in focused verification.

### 07 — Playbook lifecycle and routing

**Steps**

1. As admin, create a UAE Client Agreement playbook, add/edit a rule, and publish version 1.
2. Create version 2, delete that draft from the list, and archive the published playbook.
3. Create a matching active playbook and agreement; confirm the routed cited finding.

**Expected:** published versions are immutable; draft deletion and archive confirmations work;
the most specific eligible published playbook is selected.

**Actual:** **Pass with note** — 2/2 lifecycle tests passed on rerun. The first cold run
timed out waiting for version 2 even though create/edit/publish and draft deletion requests worked.

### 08 — Search, grounded Q&A, and citations

**Steps**

1. Search for the synthetic termination language and apply agreement filters.
2. Ask the supported termination-notice question and open every citation.
3. Ask an unsupported and a conflicting question from `hostile-conflict.pdf`.

**Expected:** only authorized evidence appears; supported claims are cited; unsupported or
conflicting evidence produces an explicit refusal/conflict state.

**Actual:** **Pass** — scoped search, cited answer boundaries, and unavailable/refusal behavior
passed in release and guardrail verification.

### 09 — Revision and version comparison

**Steps**

1. Upload `client-agreement-v1.pdf`, then upload `client-agreement-v2.pdf` as its successor.
2. Compare latest versus previous and inspect text/materiality changes in both panes.
3. Open baseline and target citations and confirm version 1 remains unchanged.

**Expected:** versions are immutable and ordered; the comparison uses the correct sources,
shows material changes, and preserves low-confidence review states.

**Actual:** **Pass** — the public-release revision/comparison journey completed successfully.

### 10 — Legal and business approval

**Steps**

1. Publish a two-stage policy: `legal_reviewer`, then `business_approver`.
2. Start a review; approve legal as the reviewer and business as the approver.
3. Attempt approval as the submitter or wrong role.

**Expected:** stages activate in order, distinct eligible people decide, and self/ineligible
approval is denied without advancing the workflow.

**Actual:** **Pass** — routed two-stage approval completed; authorization/self-approval
contracts passed in the focused suite.

### 11 — Request changes and final packages

**Steps**

1. On one review choose **Request changes** and verify terminal `revision_requested` state.
2. Upload the next immutable agreement version and start its successor review; reload the timeline.
3. Complete a separate review, poll package metadata on `503` using `Retry-After`, then download PDF and JSON.

**Expected:** old decisions do not transfer; the successor references the new version; timeline
persists; stored PDF/JSON checksums match package metadata.

**Actual:** **Partial** — Request changes persisted as workflow state
`revision_requested`; Version 2 completed; a distinct successor review opened on Version 2
with no inherited decisions; reload and final PDF/JSON checksum checks passed. The old review
case and page still display `Open`, so the terminal state is not represented consistently.

### 12 — Permanent deletion and immutable audit

**Steps**

1. Permanently delete a synthetic agreement and confirm the asynchronous accepted state.
2. Poll deletion status; then attempt detail, search, citation, review, package, and raw download access.
3. Verify the terminal deletion audit remains while owned LocalStack objects are gone.

**Expected:** deletion is durable and idempotent; content is inaccessible; only the minimal
scrubbed tombstone and immutable audit evidence remain.

**Actual:** **Pass** — API, worker, RLS, LocalStack, and audit deletion coverage passed.

### 13 — Critical API workflow in Insomnia

**Steps**

1. Use the checked-in collection and PKCE setup to call health and capabilities.
2. Upload, create/process an agreement, list versions, create a comparison, search, and read a review/package.
3. Repeat the same processing/comparison idempotency key, submit one malformed request, and test foreign scope.

**Expected:** success codes match the table above; idempotent repeats do not duplicate work;
validation is `422`; async package polling honors `Retry-After`; foreign scope is non-disclosing.

**Actual:** **Pass** — all collection operations/required parameters matched live OpenAPI and
the representative API-backed browser journeys completed.

### 14 — Recovery, hostile input, privacy, and keyboard use

**Steps**

1. Run `RESILIENCE_TEST_CONFIRM=isolated make resilience-local` with other heavy local stacks paused.
2. Upload malformed/oversized/hostile synthetic fixtures; inspect safe UI errors and logs.
3. Navigate the cited-review flow using keyboard only and verify visible focus and named controls.

**Expected:** duplicate delivery produces one result; provider exhaustion is durable and safe;
restart/database recovery completes; hostile files are bounded; no secrets/PII leak; keyboard
navigation reaches citations and decisions. The local queue-to-processing-start objective is under 5 seconds.

**Actual:** **Partial** — duplicate/provider/security/privacy/keyboard behavior passed. The
restart objective was variable: 4.771 seconds once, but 6.234, 6.619, and 5.776 seconds in
three other runs. This is disclosed as an unresolved local timing limitation.

[Back to contents](#contents)

## Evidence and cleanup

Keep evidence concise and synthetic:

- one terminal summary for setup/health, provider smoke, focused security, and resilience;
- one cropped screenshot for repository/analysis, search/citations, comparison, and approval;
- the tested date/commit and result table above;
- no passwords, keys, cookies, bearer tokens, real names, real documents, or raw prompts.

After testing:

```bash
STACK_ENV_FILE=.env STACK_PROJECT_NAME=agreement-intelligence \
  scripts/manual-qa-state.sh second-tenant-cleanup
make stack-check
make stack-down
```

Remove Insomnia's temporary callback, clear its private token/environment, and delete
generated ignored fixtures if they are no longer needed. Do not delete Docker volumes unless
you intentionally want a destructive local reset.

[Back to contents](#contents)
