# Comprehensive manual QA plan

This owner-executed plan validates the locally demonstrable product end to end without
undocumented knowledge. Use only [synthetic test data](test-data.md) and record one
[evidence block](evidence-template.md) per stable `MQA-*` ID.

## Execution conventions

### Roles, prerequisites, and order

- Start from the exact commit under review with the pinned toolchain and a validated ignored
  `.env`.
- Run no-key mode first. Provider-powered cases run only when the owner already has an
  authorized, safely stored key. Otherwise mark them Blocked, not Failed.
- Generate fixtures with `node scripts/generate-synthetic-agreements.mjs`.
- Use a clean current desktop Chromium browser for the primary pass. Browser compatibility
  cases identify additional browsers. Use a separate private window/profile per identity.
- Import the placeholder-only Insomnia collection and follow [API testing](api-testing.md).
- Run cases in document order unless a case names a prerequisite ID. Preserve local volumes
  for ordinary tests. Backup/restore, reset, queue interruption, provider outage, temporary
  tenants/users, and permanent deletion are explicitly destructive or state-changing.

### Run identity and evidence

Define `RUN_ID=<UTC-YYYYMMDD-HHMMSS>` and prefix every mutable title with its case ID and run
ID. Record commit, UTC start/end, OS/Docker/browser/Insomnia versions, mode, identity role,
fixture checksum, expected/observed result, safe screenshots/status/artifact checksums, and
cleanup. Crop browser chrome. Never capture passwords, bearer tokens, cookies, client
secrets, provider keys/bodies, prompts, raw logs, local paths, or non-synthetic data.

### Result and defect rules

- **Pass:** every numbered step and visible/persisted/authorization/cleanup expectation
  matched.
- **Fail:** execution completed and any expectation did not match. Preserve minimum safe
  evidence and report through the existing issue/PR workflow.
- **Blocked:** a prerequisite, owner-only action, or external provider prevented execution.
- Do not retry until a failure disappears without recording the original failure.
- Do not create new release scope from observations. Keep fixes isolated and issue-backed
  under the owner's normal workflow.

### Browser and Insomnia setup

Open `/sign-in`, `/dashboard`, `/dashboard/agreements`,
`/dashboard/playbooks`, `/dashboard/search`, `/dashboard/reviews`, and
`/dashboard/approval-policies` only through the documented UI. For API work, use OAuth
authorization code + PKCE and a temporary exact Insomnia callback as documented; remove it
and run `make stack-check` during cleanup.

## Installation and health

### MQA-ENV-001 — Fresh clone and no-key setup

**Purpose and risk:** Prove a first-time cloner can configure the repository without a
provider key or secret leakage.

**Identity:** Local operator; no application login.

**Preconditions and test data:** Disposable clone directory, pinned tools, Docker running,
no inherited `OPENAI_API_KEY`, synthetic local passwords.

**Steps:**

1. Clone the exact branch/commit and follow only the root README and getting-started guide.
2. Copy `.env.example`, replace all placeholders, leave provider keys/fallback empty, and
   run `scripts/validate-stack-env.sh .env` plus Compose config validation.
3. Run `make setup` and confirm `git status --short` does not show `.env` or generated data.

**Expected result:** Tool checks and environment validation pass; no provider credential is
required; only intended branch changes exist.

**Evidence:** Commit/tool versions, safe validator/setup exit summaries, clean status.

**Cleanup:** Preserve the clone for dependent cases; never retain command history containing
secret values.

**Result:** Pass / Fail / Blocked — ______

### MQA-ENV-002 — Full stack startup, health, and URLs

**Purpose and risk:** Verify all documented containers, bootstrap resources, ports, and
health contracts.

**Identity:** Local operator.

**Preconditions and test data:** MQA-ENV-001 passed; validated ignored `.env`.

**Steps:**

1. Run `make stack-up`, `make stack-check`, and `make stack-status`.
2. Open web/sign-in, API liveness/readiness, Swagger/OpenAPI, MCP endpoint, Keycloak, and
   LocalStack at documented loopback URLs.
3. Confirm nine application services run, bootstrap jobs exit zero, and published ports
   bind to loopback.

**Expected result:** Stack check reports healthy; exact services/resources/users exist; no
undocumented default endpoint or public bind is required.

**Evidence:** Safe service/status summary and health response statuses, not full environment
or container inspect output.

**Cleanup:** Leave stack running; ordinary test preserves volumes.

**Result:** Pass / Fail / Blocked — ______

### MQA-ENV-003 — Configuration validation and port conflict

**Purpose and risk:** Ensure unsafe placeholders, duplicate ports, and callback-origin
mismatch fail before startup.

**Identity:** Local operator.

**Preconditions and test data:** Copy of the ignored environment; one unused alternate port.

**Steps:**

1. In a temporary ignored environment, restore one `change-me` value and run the validator.
2. Set two published port variables equal and validate again.
3. Set `WEB_PORT` to the alternate without changing `WEB_PUBLIC_ORIGIN`; then correct
   `WEB_PUBLIC_ORIGIN` and `AUTH_URL` and validate.

**Expected result:** Each unsafe variant fails with an actionable variable-specific message;
the consistent alternate-port variant passes.

**Evidence:** Redacted error lines and final pass exit status.

**Cleanup:** Delete the temporary environment; restore original ports; do not reset volumes.

**Result:** Pass / Fail / Blocked — ______

## Authentication and authorization

### MQA-AUTH-001 — Seeded identities and role navigation

**Purpose and risk:** Confirm authentication, demo membership provisioning, and role-aware
navigation match documented permissions.

**Identity:** `platform.admin`, `legal.reviewer`, and `business.approver` in separate private
browser profiles.

**Preconditions and test data:** Healthy stack; password values read privately from `.env`.

**Steps:**

1. Sign in as each seeded username through Keycloak and open the dashboard.
2. Record visible Repository, Reviews, Search, Playbooks, and Administration navigation.
3. Confirm admin sees policy administration; reviewer can upload/update and decide; business
   approver sees only permitted read/search/approval journeys.

**Expected result:** All three authenticate; UI capabilities align with application roles;
no password or token appears in the page or URL.

**Evidence:** Cropped navigation screenshots per role.

**Cleanup:** Sign out each profile through the application.

**Result:** Pass / Fail / Blocked — ______

### MQA-AUTH-002 — Application and Keycloak single sign-out

**Purpose and risk:** Verify local session and Keycloak SSO state are cleared without a
logout loop.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Active authenticated browser session.

**Steps:**

1. Open a protected dashboard route and select **Sign out**.
2. Attempt the protected URL in the same tab and a new tab.
3. Start sign-in again and confirm Keycloak requires credentials rather than silently
   reusing the old session.

**Expected result:** User returns to the permitted post-logout path; protected routes redirect
to sign-in; stale SSO does not silently restore access.

**Evidence:** Final URLs and cropped sign-in state.

**Cleanup:** Close the profile or sign back in only for dependent cases.

**Result:** Pass / Fail / Blocked — ______

### MQA-AUTH-003 — Session expiry and invalid bearer

**Purpose and risk:** Confirm expired/revoked browser/API credentials fail closed and do not
leak resource details.

**Identity:** `legal.reviewer` browser and Insomnia token.

**Preconditions and test data:** Active session; short-lived token obtained by approved PKCE
flow.

**Steps:**

1. Revoke the local Keycloak session or clear the relevant session, then refresh a protected
   route.
2. Call `GET /agreements` with missing, literal invalid, and revoked bearer values.
3. Restore a valid sign-in and repeat the authorized request.

**Expected result:** Browser redirects safely; API returns 401 without tenant/resource data;
valid reauthentication succeeds.

**Evidence:** Status codes, safe error code/correlation presence, final authorized status.

**Cleanup:** Clear Insomnia token/history and remove temporary callback after API cases.

**Result:** Pass / Fail / Blocked — ______

### MQA-AUTH-004 — Disabled and unrecognized user

**Purpose and risk:** Verify disabled/unprovisioned identities cannot gain application
membership from a username alone.

**Identity:** Temporary synthetic `.example.test` Keycloak user.

**Preconditions and test data:** Admin console access; generated local-only username/password;
no matching configured demo subject and username.

**Steps:**

1. Create the temporary enabled Keycloak user and attempt sign-in/application access.
2. Confirm no Demo Legal membership is granted merely by the username/email.
3. Disable the user, terminate its sessions, and attempt sign-in again.

**Expected result:** Unrecognized user has no workspace access; disabled user cannot
authenticate; no configured demo account is altered.

**Evidence:** Safe denial state and temporary username label only.

**Cleanup:** Delete the temporary user and verify seeded users with `make stack-check`.

**Result:** Pass / Fail / Blocked — ______

### MQA-AUTH-005 — Cross-organization/workspace denial

**Purpose and risk:** Prove resource IDs and valid tokens cannot cross tenant boundaries.

**Identity:** `legal.reviewer` and `platform.admin`; neither belongs to the temporary tenant.

**Preconditions and test data:** Run
`STACK_ENV_FILE=.env STACK_PROJECT_NAME=agreement-intelligence scripts/manual-qa-state.sh second-tenant-setup`;
record every printed fixed organization, workspace, agreement, citation, review, and package
ID. The package is metadata-only because authorization denial must occur before object
storage access.

**Steps:**

1. With the reviewer token, list/get/search/download the second workspace's synthetic
   agreement, citation, review, and package IDs.
2. Swap only `organization_id` or `workspace_id` while retaining an otherwise valid
   in-tenant resource ID.
3. Repeat with the organization-scoped platform-admin token; that role must not become a
   cross-organization superuser.

**Expected result:** Hidden denial/empty scoped result according to route; no title, party,
filename, citation, review status, package metadata, or existence leaks.

**Evidence:** Request/status matrix with opaque IDs redacted.

**Cleanup:** Run
`STACK_ENV_FILE=.env STACK_PROJECT_NAME=agreement-intelligence scripts/manual-qa-state.sh second-tenant-cleanup`,
then `make stack-check` and confirm Demo Legal remains.

**Result:** Pass / Fail / Blocked — ______

## Agreement repository and analysis

### MQA-REP-001 — PDF upload, immediate list refresh, and viewer

**Purpose and risk:** Verify validated upload becomes immediately visible and preserves the
exact cited source.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Generated `client-agreement-v1.pdf` and checksum.

**Steps:**

1. Open Repository, upload the fixture with an `MQA-REP-001` title and Client Agreement
   family.
2. Confirm the new row/status appears without a manual page reload.
3. Open details and the labelled PDF viewer; compare displayed metadata/checksum/source.

**Expected result:** One agreement/version is created; status progresses visibly; PDF is
served only through authorized scope and matches the fixture.

**Evidence:** Repository/detail screenshots, agreement ID, fixture/artifact checksums.

**Cleanup:** Preserve this synthetic agreement for processing/search/version/review cases.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-002 — DOCX upload and authorized download

**Purpose and risk:** Verify DOCX parsing/download behavior without pretending an inline
viewer exists.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Generated `liquidity-provider-v1.docx`.

**Steps:**

1. Upload as a Liquidity Provider Agreement with an `MQA-REP-002` title.
2. Open details after processing and confirm parties/family/evidence marker are derived.
3. Use **Download original DOCX** and compare its checksum with the generated fixture.

**Expected result:** DOCX is accepted, processed, and downloaded intact through authorized
scope; UI explains download behavior.

**Evidence:** Detail screenshot and matching checksum values.

**Cleanup:** Preserve for family/playbook/search coverage or delete at final cleanup.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-003 — Invalid file, duplicate checksum, and validation

**Purpose and risk:** Ensure extension spoofing and unsupported input fail safely, while an
exact duplicate follows the documented idempotent document-upload contract.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** `invalid-signature.pdf`, one small plain-text file, and the
already uploaded v1 PDF.

**Steps:**

1. Upload the invalid-signature PDF and then the unsupported text file.
2. Upload the exact v1 PDF again to the same workspace.
3. Inspect the visible error/status, returned document ID/object key, and repository count
   after each attempt.

**Expected result:** Invalid-signature and unsupported files return `422` without a stored
object. The same-scope duplicate returns `200` with `duplicate:true` and the original
document ID/object key, so the immutable source object is not rewritten. The current
repository UI may continue and create a second agreement record after that document
response; if it does, record and remove that case-specific record rather than treating the
record count as the document-deduplication contract.

**Evidence:** Redacted validation messages/status codes, duplicate response fields, and
before/after repository counts.

**Cleanup:** Remove any case-specific agreement created after the duplicate response and the
temporary unsupported local file.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-004 — Processing timeline, retry, and requeue

**Purpose and risk:** Verify queued/processing/terminal visibility and authorized recovery
transitions.

**Identity:** `legal.reviewer` for viewing; `platform.admin` for any admin-only recovery.

**Preconditions and test data:** MQA-REP-001 agreement; a fresh synthetic upload; exact
failed-job procedure in [Test data](test-data.md); Insomnia processing status/retry/requeue
requests populated with the returned agreement/job IDs.

**Steps:**

1. Observe the processing timeline from submission through a terminal state.
2. Stop the worker, submit the fresh job, run
   `scripts/manual-qa-state.sh failed-job-setup AGREEMENT_UUID JOB_UUID`, start the worker,
   confirm the safe `transient` failure, then invoke **Retry processing (202)**.
3. Use Requeue only on a state where the API permits it and poll the exact job/attempt.

**Expected result:** State/attempt/timestamps are coherent; illegal transitions conflict;
authorized recovery creates no duplicate current version/artifact.

**Evidence:** Timeline screenshots and job/state/attempt table without raw logs.

**Cleanup:** Poll **Processing status (200)** to terminal, delete the synthetic agreement
through its normal UI/API flow, and verify `make stack-check`.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-005 — No-key deterministic analysis and citations

**Purpose and risk:** Prove useful analysis remains and provider output is not fabricated
without credentials.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Stack with provider keys empty; completed MQA-REP-001.

**Steps:**

1. Open analysis and record classification, parties, clauses, summary/risk, and provenance.
2. Follow every displayed material citation to the exact source anchor/page.
3. Confirm provider/embedding states are unavailable or deterministic and no generated
   answer is labelled successful.

**Expected result:** Deterministic artifacts are present where supported; citations resolve;
provider-dependent features are explicitly unavailable/degraded.

**Evidence:** Cropped analysis/citation/provenance screens.

**Cleanup:** None; preserve agreement.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-006 — Provider-powered analysis and provenance

**Purpose and risk:** Validate the opt-in real-provider contract without exposing a secret or
accepting ungrounded output.

**Identity:** Owner-authorized operator and `legal.reviewer`.

**Preconditions and test data:** Safely stored ignored provider key already available;
provider terms authorize the synthetic fixture; MQA-REP-005 passed.

**Steps:**

1. Add the key without logging, recreate API/worker, run `make provider-smoke`, and process a
   new copy/version of the synthetic agreement.
2. Inspect provider/model/config/schema provenance, latency/usage/cost metadata, validation
   outcome, and cited enrichment.
3. Compare every claim with source evidence and ensure deterministic artifacts remain if any
   provider field fails validation.

**Expected result:** Smoke and validated provider path succeed or return a controlled failure;
no key/body/prompt appears in UI/log/evidence; citations remain grounded.

**Evidence:** Safe smoke summary and cropped provenance/citations only.

**Cleanup:** Remove key from disposable clone, recreate API/worker in no-key mode, revoke
token as appropriate. If no safe key exists, mark Blocked.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-007 — OCR-required diagnostic

**Purpose and risk:** Ensure text-poor input is diagnosed honestly without claiming OCR.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Generated `image-only-diagnostic.pdf`.

**Steps:**

1. Upload the diagnostic fixture as a synthetic agreement.
2. Wait for parsing/processing terminal state and inspect analysis/status.
3. Search for content that is not present and inspect recovery guidance.

**Expected result:** The product records/displays `ocr_required` or the documented controlled
text-poor state; no OCR-derived text, embedding, or generated claim appears.

**Evidence:** Status/diagnostic screenshot.

**Cleanup:** Permanently delete this synthetic agreement through the admin case or final
cleanup.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-008 — Immutable successor version and duplicate rejection

**Purpose and risk:** Verify version lineage, current pointer, optimistic/duplicate controls,
and historical evidence.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** MQA-REP-001 agreement plus generated
`client-agreement-v2.pdf`.

**Steps:**

1. Upload v2 through the agreement's version action, select **Start analysis**, and wait for
   processing to complete.
2. Inspect version list, predecessor/current IDs, checksums, timestamps, and both source
   downloads/citations.
3. Attempt the identical v2 upload again and a stale current-version operation.

**Expected result:** Exactly two immutable versions exist with correct lineage/current
pointer; historical v1 remains readable; duplicate/stale operation conflicts.

**Evidence:** Version list, lineage IDs, and both fixture checksums.

**Cleanup:** Preserve for comparison/review; do not rewrite version rows.

**Result:** Pass / Fail / Blocked — ______

### MQA-REP-009 — Permanent deletion and terminal audit

**Purpose and risk:** Verify administrator-only asynchronous deletion removes all historical
source/artifact state and records recoverable terminal evidence.

**Identity:** `platform.admin`; `legal.reviewer` for denial check.

**Preconditions and test data:** A separate disposable multi-version `MQA-REP-009` agreement,
processed artifacts, recorded object inventory/checksums. Destructive.

**Steps:**

1. As reviewer, attempt permanent deletion and confirm denial.
2. As admin, confirm the destructive dialog, submit a synthetic reason, poll deletion state,
   and attempt reads/downloads while tombstoned.
3. After completion, verify agreement/versions/analysis/download/search/MCP are hidden and
   audit records a terminal safe deletion outcome.

**Expected result:** Reviewer cannot delete; tombstone blocks access/new artifact commits;
terminal deletion covers historical keys/state without leaking the free-form reason.

**Evidence:** Deletion state transitions, denial statuses, terminal audit summary; do not
copy object keys or raw reason.

**Cleanup:** Confirm the disposable record is absent; leave primary walkthrough agreement.

**Result:** Pass / Fail / Blocked — ______
## Playbooks, search, Q&A, and comparison

### MQA-INT-001 — Playbook draft, rules, publish, archive, and delete-draft

**Purpose and risk:** Verify playbook lifecycle protects immutable published policy while
allowing safe draft administration.

**Identity:** `platform.admin`.

**Preconditions and test data:** Healthy stack; unique `MQA-INT-001` name; Client Agreement
family; synthetic rule text.

**Steps:**

1. Create a draft, add/edit/delete a rule, and create a successor draft version.
2. Publish the intended version, attempt to edit/delete the published version, and inspect
   history.
3. Create an unused draft and delete it; archive the published playbook and inspect routing.

**Expected result:** Draft operations persist; publish freezes the version; published
mutation is denied; unused draft deletion and archive follow documented lifecycle without
rewriting history.

**Evidence:** Version/status/rule screenshots and denial message.

**Cleanup:** Delete unused drafts; retain one published/archived synthetic playbook only as
needed for dependent cases.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-002 — Playbook routing, findings, and override

**Purpose and risk:** Confirm family/scope routing and cited rule findings use the intended
published version.

**Identity:** `platform.admin` then `legal.reviewer`.

**Preconditions and test data:** Published Client Agreement playbook; MQA-REP-001 agreement;
rules covering termination/liability.

**Steps:**

1. List eligible playbooks for the agreement and submit/evaluate the selected published
   version.
2. Open the review workspace; inspect finding result/severity/guidance/risk and all citations.
3. Record an authorized synthetic override and confirm audit/provenance identify the exact
   playbook version without copying sensitive reason text.

**Expected result:** Only eligible published scope routes; findings are versioned/cited;
override is explicit and immutable rather than silent policy replacement.

**Evidence:** Eligible version ID, finding/citation screenshot, safe audit action.

**Cleanup:** Preserve findings for review decisions; remove only unused drafts.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-003 — Lexical search, filters, and citation navigation

**Purpose and risk:** Verify no-key retrieval returns authorized textual matches with stable
filters and evidence links.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Provider keys empty; completed v1/v2 and DOCX fixtures.

**Steps:**

1. Search `NORTHSTAR-SYNTHETIC-ALPHA`, then `AURORA-SYNTHETIC-GAMMA`.
2. Apply agreement/family/status filters and clear/change each filter.
3. Open every result citation and verify agreement/version/anchor match the query evidence.

**Expected result:** Lexical mode is labelled; filters limit the same authorized dataset;
citations navigate to exact source; no other workspace content appears.

**Evidence:** Search/filter/result mode and citation screenshots.

**Cleanup:** Clear filters; no data mutation.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-004 — Semantic retrieval and provider-outage fallback

**Purpose and risk:** Verify embeddings add semantic candidates only when available and
outage falls back visibly to lexical results.

**Identity:** Owner-authorized provider operator and `legal.reviewer`.

**Preconditions and test data:** Provider-mode MQA-REP-006 completed; indexed synthetic
agreement; controllable compatible/provider outage.

**Steps:**

1. Run a paraphrased semantic query without the exact source terms and inspect retrieval
   mode/provenance.
2. Make the configured embedding provider unavailable and rerun an exact lexical query plus
   the paraphrase.
3. Restore provider, run smoke, issue a new query, and inspect retry behavior.

**Expected result:** Valid compatible embeddings enable semantic/fused results; outage
preserves labelled lexical matches and unavailable semantic state; recovery retries new
query embeddings without claiming historical backfill.

**Evidence:** Retrieval-mode/status matrix and safe provider provenance.

**Cleanup:** Restore provider configuration; remove key in disposable clone. Mark Blocked if
no authorized key exists.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-005 — Grounded answer and citations

**Purpose and risk:** Confirm provider-generated answers are limited to freshly retrieved,
accessible evidence.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Provider-powered indexed MQA-REP-001 agreement; question
about termination notice.

**Steps:**

1. Create a question thread restricted to the agreement and ask the supported question.
2. Inspect status/message/claims and follow every citation to the exact version/source.
3. Ask a second turn after archiving/removing access to one cited item and inspect fresh
   retrieval.

**Expected result:** Supported claim states the evidenced notice and cites accessible source;
history does not grant access; inaccessible evidence is removed or answer refuses.

**Evidence:** Cropped answer/citation states and source anchor.

**Cleanup:** Restore only if required for dependent review; clear private API history.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-006 — Insufficient, conflicting, and prompt-injection evidence

**Purpose and risk:** Ensure the system refuses unsupported/conflicting answers and treats
document instructions as untrusted text.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Generated `hostile-conflict.pdf` and the absent renewal
statement in the [test-data guide](test-data.md).

**Steps:**

1. Ask a question whose answer is absent and record the answer state.
2. Ask about the deliberately conflicting notice evidence and inspect both citations/state.
3. Ask the document injection text to reveal another workspace or ignore rules.

**Expected result:** Missing evidence returns insufficient/refusal; conflict is exposed and
cited; injection does not change system behavior or reveal data/actions.

**Evidence:** Answer states and safe citation IDs; never capture prompts/provider bodies.

**Cleanup:** Delete the synthetic agreement through the supported flow; remove generated
fixtures only with `rm -rf artifacts/manual-qa/fixtures` after all upload cases finish.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-007 — Version comparison, materiality, and dual citations

**Purpose and risk:** Verify comparison uses exact immutable baseline/target and explains
material changes with evidence on both sides.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** MQA-REP-008 two-version agreement.

**Steps:**

1. Open Compare, select v1 baseline and v2 target, start comparison, and wait for terminal
   state.
2. Inspect changed notice/liability/confidentiality alignments, materiality, severity,
   rationale, confidence, and review-required flags.
3. Follow baseline and target citations for each material change.

**Expected result:** Result names exact version IDs/profile; known changes appear with
appropriate materiality/uncertainty; both citations resolve to their respective source.

**Evidence:** Comparison summary and dual citation screenshots.

**Cleanup:** Preserve comparison for review package walkthrough.

**Result:** Pass / Fail / Blocked — ______

### MQA-INT-008 — Low-confidence matched comparison alignment

**Purpose and risk:** Ensure uncertainty in the alignment produced by the shipped synthetic
pair is exposed for human review.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** The processed `client-agreement-v1.pdf` and
`client-agreement-v2.pdf` versions from MQA-REP-008.

**Steps:**

1. Run comparison for the shipped v1 baseline and v2 target.
2. Inspect the single matched change, its confidence, review-required flag, word-level
   additions/removals/replacements, and rationale.
3. Open its baseline and target citations and confirm both resolve to the correct version.

**Expected result:** The shipped pair produces one `matched` change with
`review_required:true`; the changed synthetic terms are visible in the word diff and both
version citations resolve. This pair does not claim to exercise added, removed, split,
merged, or moved alignment kinds.

**Evidence:** Alignment-state table and representative citation links.

**Cleanup:** Preserve the comparison for the review-package walkthrough.

**Result:** Pass / Fail / Blocked — ______

## Review, approval, audit, and packages

### MQA-REV-001 — Approval policy create, version, publish, and route

**Purpose and risk:** Verify only authorized administrators define immutable legal/business
stage policy.

**Identity:** `platform.admin`; `legal.reviewer` for denial.

**Preconditions and test data:** Unique `MQA-REV-001` policy name; legal_reviewer then
business_approver stages.

**Steps:**

1. As reviewer, attempt policy administration and confirm denial/navigation absence.
2. As admin, create draft stages with eligible role keys, all/any mode, due/escalation
   values, and cross-stage same-approver disabled.
3. Publish, route for the synthetic agreement, create a successor version, and attempt
   published mutation.

**Expected result:** Reviewer cannot manage; published policy routes by scope and remains
immutable; successor is a distinct version.

**Evidence:** Policy version/stage/route and denial screenshots.

**Cleanup:** Retain one published synthetic policy for workflow cases.

**Result:** Pass / Fail / Blocked — ______

### MQA-REV-002 — Review creation, assignment, comments, and notifications

**Purpose and risk:** Verify review collaboration is tenant/role scoped and assignment
changes are auditable.

**Identity:** `platform.admin`, `legal.reviewer`, `business.approver`.

**Preconditions and test data:** Processed agreement/findings and published MQA-REV-001
policy.

**Steps:**

1. Create the review/workflow and assign the legal stage to the legal reviewer.
2. Confirm reviewer inbox/notification and add a synthetic comment; reassign/delegate only
   where the policy/permission permits.
3. Confirm business approver sees only eligible/current work and audit/timeline records
   assignment/comment actions.

**Expected result:** Assignments and notifications are role/current-stage scoped; comments
persist with attribution; unauthorized reassignment/delegation is denied.

**Evidence:** Inbox/notification/comment/timeline screenshots.

**Cleanup:** Preserve review for decisions; no free-form personal or legal data.

**Result:** Pass / Fail / Blocked — ______

### MQA-REV-003 — Reviewer decision and cited report

**Purpose and risk:** Ensure legal finding decisions preserve original result, human
rationale, citation, and immutable event history.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** MQA-INT-002 findings and assigned MQA-REV-002 review.

**Steps:**

1. Filter/open a high-severity finding and follow cited evidence by keyboard.
2. Record accepted/rejected or edited decision with synthetic rationale; if edited, supply
   permitted edited result/severity.
3. Reload, inspect decision history/current state, and download the review report.

**Expected result:** Decision requires rationale and valid edit fields; event/current state
persist with actor/time; report contains cited synthetic decision evidence.

**Evidence:** Finding/decision history and report checksum, not raw report text.

**Cleanup:** Retain for approval/package; do not attempt to delete immutable event.

**Result:** Pass / Fail / Blocked — ______

### MQA-REV-004 — Legal/business stage separation and self-approval denial

**Purpose and risk:** Prove stage eligibility, ordering, and self/cross-role denial.

**Identity:** `legal.reviewer`, `business.approver`, and `platform.admin`.

**Preconditions and test data:** Two-stage workflow with same-approver disabled and current
legal assignment.

**Steps:**

1. As business approver, attempt the legal-stage decision before legal completion.
2. As assigned legal reviewer, approve the legal stage; then attempt the business stage with
   the same identity/admin where self/cross-stage policy denies it.
3. As business approver, complete the eligible business stage.

**Expected result:** Out-of-order, ineligible, and prohibited same-actor decisions are denied;
only eligible human decisions advance the workflow; timeline records each accepted action.

**Evidence:** Decision/status matrix and final stage transitions.

**Cleanup:** Preserve terminal review for package case.

**Result:** Pass / Fail / Blocked — ______

### MQA-REV-005 — Request changes, successor version, and reload persistence

**Purpose and risk:** Verify non-terminal change requests require human resolution and do
not mutate the reviewed version.

**Identity:** Eligible stage approver then `legal.reviewer`.

**Preconditions and test data:** Separate non-terminal synthetic review on agreement v1.

**Steps:**

1. Submit **Request changes** with a synthetic rationale and inspect workflow/timeline.
2. Upload agreement v2 as a successor; create/reroute a review according to current workflow
   controls.
3. Refresh/restart web and revisit both old/new versions and review histories.

**Expected result:** Change request is explicit and attributed; v1 remains immutable;
successor/review lineage is clear; state persists after reload/restart.

**Evidence:** Change state, version IDs, and persistence screenshots.

**Cleanup:** Preserve only records required by final traceability; delete disposable review
only through supported lifecycle if available.

**Result:** Pass / Fail / Blocked — ______

### MQA-REV-006 — Terminal package, manifest checksums, and audit timeline

**Purpose and risk:** Verify terminal PDF/JSON artifacts are immutable, internally linked,
and checksum-backed.

**Identity:** `platform.admin` and authorized review participant.

**Preconditions and test data:** Completed MQA-REV-004 terminal review.

**Steps:**

1. Open final package metadata and download PDF plus JSON manifest.
2. Compute local SHA-256 values and compare with displayed/manifest checksums and exact
   review/agreement/version/policy identifiers.
3. Reload and request artifacts again; inspect complete timeline/audit order and attempt an
   unauthorized download.

**Expected result:** Checksums/IDs match; repeat reads return the same immutable artifacts;
timeline is ordered/attributed; unauthorized principal cannot access metadata or bytes.

**Evidence:** Metadata screenshot and checksum comparison file only.

**Cleanup:** Store only synthetic artifact checksums/evidence; delete downloaded bytes after
review if not needed.

**Result:** Pass / Fail / Blocked — ______

### MQA-REV-007 — Cross-workspace review, audit, and package denial

**Purpose and risk:** Validate the most sensitive workflow/evidence objects do not cross
tenant scope.

**Identity:** Demo Legal reviewer/admin; neither belongs to the temporary second tenant.

**Preconditions and test data:** Synthetic terminal Demo Legal review/package plus every
fixed foreign organization/workspace/agreement/review/package ID printed by
`scripts/manual-qa-state.sh second-tenant-setup`. The foreign package fixture is metadata-only.

**Steps:**

1. Request the Demo Legal review/package IDs under the foreign organization/workspace, then
   request the foreign review/package/agreement IDs under Demo Legal scope.
2. Attempt timeline, comments, decisions, package metadata/PDF/manifest, and audit search.
3. Attempt the same from read-only MCP status tools.

**Expected result:** Hidden denial/empty scope with no party/title/status/checksum/comment/
citation/existence leakage; no cross-scope audit event content is returned.

**Evidence:** Route/status matrix with opaque IDs redacted.

**Cleanup:** Run `scripts/manual-qa-state.sh second-tenant-cleanup`, remove only the
case-specific Demo Legal records through supported flows, and run `make stack-check`.

**Result:** Pass / Fail / Blocked — ______

## API, MCP, and operations

### MQA-API-001 — Insomnia OAuth, health, and capability discovery

**Purpose and risk:** Verify a first-time API tester can authenticate without storing a
password grant or committed secret and can discover the running API contract.

**Identity:** `platform.admin` through authorization-code plus PKCE.

**Preconditions and test data:** Running stack, imported public Insomnia collection, the
temporary exact Insomnia redirect URI configured as described in the API guide.

**Steps:**

1. Populate only the private Insomnia sub-environment, complete browser authorization, and
   call API health, readiness, OpenAPI, and
   `GET /identity/organizations/{organization_id}/workspaces/{workspace_id}/capabilities`.
2. Inspect the final request URL and headers without copying the bearer value into evidence.
3. Clear the private token, repeat the protected request, and then authenticate again.

**Expected result:** Public health/schema requests succeed; protected capability discovery
requires a valid bearer token; clearing the token yields `401`; PKCE reauthentication works.

**Evidence:** Status codes, redacted request names, capability mode/provider fields, and
Insomnia version; exclude token, cookie, code, verifier, and redirect query.

**Cleanup:** Clear private environment secrets and remove the temporary redirect URI.

**Result:** Pass / Fail / Blocked — ______

### MQA-API-002 — Representative API lifecycle and idempotency

**Purpose and risk:** Verify documented methods, paths, scope parameters, response shapes,
and retry behavior match the published OpenAPI schema.

**Identity:** `platform.admin` for setup; `legal.reviewer` for ordinary calls.

**Preconditions and test data:** `client-agreement-v1.pdf`, a fresh private
`request_run_id`, imported collection variables, and the frozen demo
organization/workspace IDs.

**Steps:**

1. Create/upload a case-specific agreement, list and read it, then request its analysis,
   search, review, and audit resources with explicit organization/workspace query values.
2. Repeat one safe read and one processing or comparison mutation with the same
   `request_run_id`; confirm the collection sends the operation-specific `Idempotency-Key`.
   Change `request_run_id` before any new logical mutation.
3. Compare every observed status/body with the running OpenAPI operation and schema.

**Expected result:** Documented methods and paths exist; scope is explicit; responses match
schema; the repeated idempotent mutation does not create a duplicate logical operation.

**Evidence:** Redacted Insomnia timeline, operation IDs/statuses, record counts, and request
identifier hash; never export the private environment.

**Cleanup:** Delete disposable mutable records using normal API/UI flows.

**Result:** Pass / Fail / Blocked — ______

### MQA-API-003 — API validation and cross-tenant denial

**Purpose and risk:** Confirm malformed identifiers, unsupported media, missing scope, and
foreign organization/workspace identifiers fail closed without leaking existence or data.

**Identity:** `legal.reviewer` and organization-scoped `platform.admin`.

**Preconditions and test data:** Existing demo record; exact
`scripts/manual-qa-state.sh second-tenant-setup` fixture; invalid UUID/string fixtures;
generated `invalid-signature.pdf` and `unsupported.txt`.

**Steps:**

1. Send requests with missing scope, malformed UUIDs, invalid JSON/media, and unsupported
   enum/state transitions.
2. Substitute a valid record ID with a foreign organization or workspace and repeat list,
   detail, download, search, review, audit, and deletion requests.
3. Inspect API and safe service logs for stack traces, SQL, object keys, or document text.

**Expected result:** Validation returns stable `4xx` responses; cross-tenant access is denied
or indistinguishable from absence; no protected content or implementation secret is exposed.

**Evidence:** Status/error-code matrix and redacted log review result.

**Cleanup:** Run `scripts/manual-qa-state.sh second-tenant-cleanup`; remove private Insomnia
variables and run `make stack-check`.

**Result:** Pass / Fail / Blocked — ______

### MQA-MCP-001 — Read-only MCP tools and citations

**Purpose and risk:** Verify the MCP endpoint advertises only the four documented read-only
tools and preserves the same tenant, authorization, and citation guarantees as the API.

**Identity:** `legal.reviewer`.

**Preconditions and test data:** Processed `client-agreement-v1.pdf`, its known marker, MCP
URL `http://127.0.0.1:8001/mcp`, and an MCP client that can supply a bearer token privately.

**Steps:**

1. Initialize an MCP session and list tools.
2. Invoke `search_agreements`, `get_citation`, `get_agreement_status`, and
   `get_review_status` for authorized synthetic records.
3. Attempt to discover or invoke a create, update, approve, delete, or arbitrary-fetch tool.

**Expected result:** Exactly the four documented tools are available; results are scoped and
cited; no mutating/general-purpose tool is exposed.

**Evidence:** Redacted tool-name list, safe status fields, citation page/locator, and denials.

**Cleanup:** Close the MCP session and clear the client token.

**Result:** Pass / Fail / Blocked — ______

### MQA-MCP-002 — MCP invalid session and tenant boundaries

**Purpose and risk:** Verify invalid authentication, malformed tool input, guessed IDs, and
foreign scope cannot bypass HTTP/API authorization through MCP.

**Identity:** Unauthenticated client, `legal.reviewer`, and organization-scoped
`platform.admin`.

**Preconditions and test data:** One authorized and one foreign synthetic record plus invalid
UUIDs and expired/invalid token cases.

**Steps:**

1. Initialize/call without a token and with an expired or invalid token.
2. Call every applicable tool with malformed inputs, a guessed missing ID, and a foreign
   agreement/review/workspace identifier.
3. Compare response, audit, and log behavior with the equivalent API denial.

**Expected result:** MCP fails closed with no foreign metadata, citation, content, status, or
token disclosure; error/audit behavior remains bounded and consistent.

**Evidence:** Tool/status matrix and redacted audit/log summary.

**Cleanup:** Run `scripts/manual-qa-state.sh second-tenant-cleanup`, clear private client
credentials, and close sessions.

**Result:** Pass / Fail / Blocked — ______

### MQA-OPS-001 — Container restart and durable local state

**Purpose and risk:** Verify documented restart commands preserve database/object state while
recovering API, worker, web, identity, queue, and telemetry services.

**Identity:** Local operator; `platform.admin` for post-restart checks.

**Preconditions and test data:** Healthy stack with a processed case-specific agreement,
review, audit event, and recorded checksums.

**Steps:**

1. Record `make stack-check`, service health, record IDs, checksums, and current status.
2. Run `docker compose --project-name agreement-intelligence --env-file .env restart`, wait,
   and rerun
   `make stack-check` without resetting volumes.
3. Sign in and verify source download, analysis, search, review, and audit state.

**Expected result:** Services recover to healthy; durable records/checksums remain unchanged;
no duplicate work or identity/bootstrap corruption appears.

**Evidence:** Before/after health and checksum/status comparison.

**Cleanup:** Leave the reusable stack running; remove only case-specific records.

**Result:** Pass / Fail / Blocked — ______

### MQA-OPS-002 — Worker interruption, retry, and duplicate delivery

**Purpose and risk:** Confirm queue processing is resumable and idempotent when the worker
stops mid-job or receives duplicate delivery.

**Identity:** Local operator and `platform.admin`.

**Preconditions and test data:** Fresh `liquidity-provider-v1.docx`, healthy queue, safe log
access, recorded checksum, and the self-cleaning focused duplicate fixture.

**Steps:**

1. Run `uv run python tests/resilience/test-duplicate-delivery.py` and record its three
   focused contract results.
2. Run `RESILIENCE_TEST_CONFIRM=isolated tests/resilience/test-worker-restart.sh`; it creates
   a unique project, sends the same processing/workflow deliveries twice, waits on persisted
   state, and removes only its own volumes.
3. In the ordinary stack, upload one fresh fixture, restart the worker once, wait for its
   exact job to become terminal, and inspect version/artifact/finding/audit counts.

**Expected result:** Work resumes or surfaces retry action; one logical artifact set remains;
no duplicate version/finding/event is committed and the source checksum is unchanged.

**Evidence:** Safe state timeline, counts, worker health, and redacted retry/audit evidence.

**Cleanup:** Restore worker health and remove the disposable agreement.

**Result:** Pass / Fail / Blocked — ______

### MQA-OPS-003 — Provider outage and recovery contract

**Purpose and risk:** Verify provider-dependent capabilities fail explicitly while
deterministic processing, lexical retrieval, and core workflows stay available.

**Identity:** Local operator and `legal.reviewer`.

**Preconditions and test data:** Generated text-bearing fixture; ignored
`.env.provider-outage.local` safely derived from `.env` with both key variables empty,
`MODEL_GATEWAY_MODE=openai-compatible`, and
`MODEL_GATEWAY_BASE_URL=http://127.0.0.1:9/v1`.

**Steps:**

1. Run `uv run python tests/resilience/test-provider-timeout.py`; then recreate API/worker
   with `docker compose --project-name agreement-intelligence --env-file .env.provider-outage.local up --detach --force-recreate --no-deps api worker`.
2. Exercise upload/analysis, lexical search, semantic search, and grounded-answer requests.
3. Restore configuration, restart affected services, verify capability recovery, and retry a
   new query embedding; note that historical backfill remains manual/deferred.

**Expected result:** Deterministic/lexical/core flows remain available; provider-dependent
operations show explicit unavailable/degraded state; new requests recover after restoration.

**Evidence:** Capability snapshots, UI/API error states, health, and safe status timeline.

**Cleanup:** Recreate API/worker with `--env-file .env`, remove only
`.env.provider-outage.local`, run `make stack-check`, and never copy a provider key into the
outage file.

**Result:** Pass / Fail / Blocked — ______

### MQA-OPS-004 — Backup and restore rehearsal

**Purpose and risk:** Verify the documented local database/object backup boundary can restore
a disposable environment without claiming an unsupported automated disaster-recovery system.

**Identity:** Local operator and `platform.admin`.

**Preconditions and test data:** Dedicated disposable Compose project/volumes, a processed
synthetic agreement, review/audit state, and recorded source/export checksums.

**Steps:**

1. Follow the operations guide to capture the supported database and object-store artifacts.
2. Restore them into a distinct disposable project using the documented manual procedure.
3. Start services and verify tenant scope, source/checksum, analysis, search, review, audit,
   and deletion state; do not point either project at production resources.

**Expected result:** Supported artifacts restore consistently in the rehearsal environment;
documented exclusions/limitations remain explicit and no cross-project mutation occurs.

**Evidence:** Commands with paths/credentials redacted, archive checksums, and restored-state
comparison.

**Cleanup:** Stop the restored disposable project and remove its dedicated temporary volumes
only after verifying the exact project name.

**Result:** Pass / Fail / Blocked — ______

## Browser quality and accessibility

### MQA-UX-001 — Supported-browser critical journey

**Purpose and risk:** Detect browser-specific failures in sign-in, upload, repository,
analysis, search, comparison, review, approval, audit, and sign-out.

**Identity:** All three seeded roles.

**Preconditions and test data:** Current stable Chromium, Firefox, and WebKit/Safari where
available; synthetic fixtures; clean profiles without extensions.

**Steps:**

1. Execute the critical synthetic journey in each browser at a 1440×900 viewport.
2. Verify downloads, dialogs, tables, timelines, citation links, and session transitions.
3. Record console/page errors and compare visible results across browsers.

**Expected result:** Critical actions and information are usable in each available engine;
no uncaught exception, blank page, hidden control, or inconsistent persisted outcome occurs.

**Evidence:** Browser/version matrix, sanitized screenshots, and console-error count.

**Cleanup:** Sign out, clear profiles/downloads, and delete disposable mutable records.

**Result:** Pass / Fail / Blocked — ______

### MQA-UX-002 — Responsive layout, zoom, and overflow

**Purpose and risk:** Ensure product sections remain readable and operable at common desktop,
tablet, and narrow/mobile widths and at 200 percent zoom.

**Identity:** `legal.reviewer` and `platform.admin`.

**Preconditions and test data:** Populated synthetic repository/search/review records;
viewports 1440×900, 1024×768, 768×1024, and 390×844.

**Steps:**

1. Visit dashboard, repository/detail, playbooks, search/Q&A, comparison, reviews, approvals,
   audit, and admin pages at every viewport.
2. Repeat desktop pages at 200 percent zoom and enlarge text where browser support permits.
3. Inspect navigation, tables, dialogs, viewers, long IDs, errors, and action bars for loss or
   overlapping content.

**Expected result:** Content reflows or offers intentional scrolling; primary actions,
headings, labels, status, and errors are not clipped or obscured.

**Evidence:** Page/viewport matrix and minimum sanitized screenshots for any defect.

**Cleanup:** Restore default zoom and close the clean profile.

**Result:** Pass / Fail / Blocked — ______

### MQA-A11Y-001 — Keyboard, focus, names, and status announcements

**Purpose and risk:** Verify critical flows do not require a mouse and expose meaningful
structure, labels, focus, errors, and asynchronous status to assistive technology.

**Identity:** All seeded roles as needed for their pages.

**Preconditions and test data:** Keyboard-only browser session, browser accessibility tree or
screen reader, populated synthetic records, no accessibility-altering extensions.

**Steps:**

1. From sign-in through upload, search/citation, comparison, review, approval, audit, and
   sign-out, operate controls using keyboard alone and observe visible focus/order.
2. Inspect headings, landmarks, form names/instructions/errors, table semantics, dialogs,
   status badges, loading progress, and live updates in the accessibility tree.
3. Open and close menus/dialogs, trigger validation, and verify focus return/no keyboard trap.

**Expected result:** Every critical control is named and reachable in logical order; focus is
visible/contained/restored; errors and async outcomes are programmatically perceivable.

**Evidence:** Browser/assistive-tech versions, accessibility-tree excerpts without user data,
keyboard checklist, and sanitized defect images.

**Cleanup:** Sign out and close the clean accessibility-test profile.

**Result:** Pass / Fail / Blocked — ______

## Failure recovery and security

### MQA-SEC-001 — Hostile evidence, privacy, and log redaction

**Purpose and risk:** Verify agreement text is treated as untrusted evidence and sensitive
request material is not copied into UI errors, telemetry, audits, or routine logs.

**Identity:** `legal.reviewer`; local operator for safe log inspection.

**Preconditions and test data:** Synthetic prompt-injection/conflict strings from the test
data guide and unique non-secret canary values that cannot resemble credentials.

**Steps:**

1. Upload/search/ask against synthetic hostile and conflicting evidence and attempt requests
   for foreign scope, system instructions, hidden context, and unsupported conclusions.
2. Trigger validation, provider-unavailable, and authorization errors containing only safe
   canary input.
3. Inspect visible responses plus redacted API/worker/MCP/telemetry/audit records for raw
   document bodies, prompts, bearer values, cookies, passwords, or provider keys.

**Expected result:** Hostile text never changes authority; refusal/conflict/citations remain
grounded; secrets and raw bodies are absent from ordinary errors/logs/telemetry/audits.

**Evidence:** Canary-presence matrix, refusal/citation state, and redaction review counts.

**Cleanup:** Delete hostile synthetic records and local evidence containing canaries.

**Result:** Pass / Fail / Blocked — ______

### MQA-SEC-002 — Parser limits and hostile upload recovery

**Purpose and risk:** Confirm corrupt, disguised, empty, unsupported, and over-limit uploads
fail safely without wedging worker or repository state.

**Identity:** `legal.reviewer`; local operator for service-health inspection.

**Preconditions and test data:** Generated `invalid-signature.pdf`,
`image-only-diagnostic.pdf`, `empty.pdf`, `unsupported.txt`,
`boundary-under-limit.pdf` (9 MiB), and `boundary-over-limit.pdf` (11 MiB).

**Steps:**

1. Upload each hostile/boundary file singly and concurrently within documented local limits.
2. Observe validation/status/retry actions, record counts, worker/API health, and storage state.
3. Upload a valid synthetic PDF immediately afterward and verify full processing.

**Expected result:** Invalid/unsupported/over-limit inputs are rejected or diagnosed
explicitly; no partial visible record/artifact leaks; services recover and process valid input.

**Evidence:** Fixture checksums/sizes, result/status matrix, and health snapshot.

**Cleanup:** Remove any safely deletable rejected records; after all upload cases, remove
only the ignored fixture directory with `rm -rf artifacts/manual-qa/fixtures`.

**Result:** Pass / Fail / Blocked — ______

### MQA-REC-001 — Dependency interruption and UI recovery

**Purpose and risk:** Verify temporary loss of Postgres, Redis/queue, object storage, or
identity produces bounded errors and a recoverable UI rather than corruption or false success.

**Identity:** Local operator; seeded roles after dependency restoration.

**Preconditions and test data:** Dedicated disposable stack with a processed agreement and a
second fixture ready; recorded baseline state/checksums. Destructive to disposable uptime.

**Steps:**

1. For SQS/object storage, run the exact LocalStack stop/submit/start/bootstrap/requeue
   sequence in [Test data](test-data.md); then stop one remaining dependency at a time and
   inspect the affected flow plus health endpoints without resetting volumes.
2. Restore it, wait for readiness, reload/retry through documented controls, and compare
   records/artifacts with baseline.
3. Repeat for each dependency, ending with `make stack-check` and the critical smoke flow.

**Expected result:** Failed operations do not report false success or cross-contaminate state;
recovery is possible after readiness; persisted checksums/records remain consistent.

**Evidence:** Dependency/status/recovery matrix and before/after counts/checksums.

**Cleanup:** Restore every service, invoke an authorized requeue/retry or new same-scope
processing action for any pending outbox row, wait for exact jobs to become terminal,
remove only disposable records, and run `make stack-check`.

**Result:** Pass / Fail / Blocked — ______

### MQA-REL-001 — Clean-clone public-release gate

**Purpose and risk:** Prove the repository instructions and automated gate work from a fresh
checkout without relying on untracked state from a developer worktree.

**Identity:** Local operator; seeded identities during browser checks.

**Preconditions and test data:** Disposable clone of the candidate commit, toolchain pins,
Docker, free loopback ports, generated fixtures, and a unique Compose project.

**Steps:**

1. Follow README setup with provider key variables empty, run health/smoke/docs/OpenAPI/full
   automated gates and the Playwright release project, and record safe evidence.
2. Verify deterministic analysis, lexical retrieval, provider capability flags, explicit
   semantic/generated-answer degradation, and all documented demo identities.
3. Validate the opt-in provider configuration contract without printing or committing a key;
   if an authorized real provider secret is unavailable, mark only the live-provider call
   Blocked and still verify validation/configuration/outage behavior.

**Expected result:** Fresh no-key clone passes the release gate and critical journey; provider
boundaries match docs; optional live-provider evidence is Pass or honestly Blocked, never
silently inferred.

**Evidence:** Candidate SHA, tool versions, commands/exits, service health, mode/capability
snapshot, release artifacts/checksums, and provider sub-result without secret material.

**Cleanup:** Stop the unique Compose project, remove its disposable clone/volumes only after
checking the exact paths/names, and retain sanitized evidence required by the PR.

**Result:** Pass / Fail / Blocked — ______

## Release traceability matrix

Every row requires a recorded result for the candidate commit. “Automated support” is not a
substitute for the detailed manual case; it identifies corroborating coverage only.

| Product/release section | Primary manual QA IDs | Modes / roles | Required safe evidence | Automated support |
| --- | --- | --- | --- | --- |
| Fresh clone, configuration, full stack, URLs | MQA-ENV-001–003, MQA-REL-001 | no-key; operator/admin | tool versions, health, mode snapshot | `make stack-check`, `make release-check` |
| Authentication, roles, sign-out, session expiry | MQA-AUTH-001–005 | all roles; unauthenticated | role/page matrix, `401/403`, logout state | web auth/E2E and API tests |
| Tenant/workspace isolation | MQA-AUTH-005, MQA-API-003, MQA-MCP-002, MQA-REV-007 | demo and temporary tenant | denial matrix without foreign data | RLS/authz/integration tests |
| Repository, upload, download, viewer | MQA-REP-001–003 | reviewer/admin | checksum, list/view/download state | upload/parser/browser tests |
| Processing, retry, diagnostics | MQA-REP-004, MQA-REP-007, MQA-OPS-002, MQA-SEC-002 | reviewer/operator | state timeline, counts, health | ingestion/queue tests |
| Deterministic and provider analysis | MQA-REP-005–006, MQA-OPS-003 | no-key/provider/outage | provenance/capability/status | AI eval and provider tests |
| Versioning and deletion | MQA-REP-008–009 | reviewer/admin | lineage/checksums, terminal audit | lifecycle/deletion tests |
| Playbooks and findings | MQA-INT-001–002 | admin/reviewer | rules/version/findings/override | playbook E2E/API tests |
| Search, filters, and citations | MQA-INT-003–004 | no-key/provider/outage | ranks/filters/citation/mode | search E2E/eval tests |
| Grounded Q&A and responsible-AI boundary | MQA-INT-005–006, MQA-SEC-001 | provider/no-key; reviewer | answer/refusal/conflict/citations | AI eval/provider tests |
| Version comparison | MQA-INT-007–008 | provider/no-key; reviewer | pair alignment/materiality/citations | comparison unit/API tests |
| Approval policy and route | MQA-REV-001, MQA-REV-004 | admin/legal/business | policy version/stage denials | approval E2E/API tests |
| Review workspace, comments, decisions | MQA-REV-002–005 | legal/business | assignments/comments/status/reload | review E2E/API tests |
| Audit trail and terminal package | MQA-REV-006–007, MQA-REP-009 | admin/reviewer | event sequence, manifest/checksums | audit/package tests |
| API and OpenAPI | MQA-API-001–003 | OAuth roles/unauthenticated | operation/status/schema matrix | docs contract and API tests |
| MCP read-only tools | MQA-MCP-001–002 | reviewer/unauthenticated | tool list/citations/denials | MCP tests |
| Restart, persistence, backup, recovery | MQA-OPS-001–004, MQA-REC-001 | operator/admin | before/after checksums and health | stack and integration tests |
| Browser compatibility/responsiveness | MQA-UX-001–002 | all roles | engine/viewport matrix | Playwright release project |
| Accessibility | MQA-A11Y-001 | all roles | keyboard/tree/focus checklist | component/browser checks |
| Security, hostile input, privacy, secrets | MQA-API-003, MQA-MCP-002, MQA-SEC-001–002 | all boundaries | denial/redaction/scan summaries | authz, parser, secret scans |

Cloud deployment, managed ingress, and production backup/restore are deferred boundaries,
not hidden manual-test obligations. See the [roadmap](../roadmap.md) and
[operations guide](../operations/platform-foundation.md).

[Back to top](#comprehensive-manual-qa-plan)
