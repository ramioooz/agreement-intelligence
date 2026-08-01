# Sprint 3 — Playbook Risk Review Design

## Goal

Deliver a legal-review workflow in which a platform administrator defines a versioned agreement-family playbook, the system evaluates an analysed agreement against its published rules, and a legal reviewer can inspect cited findings, record an append-only decision, and export a cited review report.

## Scope and delivery order

Sprint 3 is delivered as seven independently reviewable pull requests, in dependency order:

1. #21 — versioned legal playbooks and clause positions.
2. #22 — playbook administration UI.
3. #23 — deterministic rule evaluation and persisted findings.
4. #24 — policy-bounded risk explanations.
5. #25 — playbook-aligned fallback suggestions.
6. #26 — clause-centric review workspace.
7. #27 — append-only reviewer decisions and export.

Stories #22–#24 may begin after #21’s API contract is merged. Stories #25 and #26 may begin after the finding contract from #23 and #24 is merged. #27 follows the persisted finding contract and review workspace. Every UI-bearing story includes Playwright coverage against the containerized stack and a final browser smoke check.

## Authorization and tenancy

All new resources are scoped by organization and workspace. The application API, not browser role claims, is authoritative for access decisions.

- `playbooks:manage`: granted only to platform administrators in Sprint 3; allows creating drafts, changing draft rules, publishing a draft, and retiring a draft.
- `agreements:review`: granted to platform administrators and legal reviewers; allows reading published playbooks, findings, evidence, and recording reviewer decisions.
- No role may mutate a published version. Published versions are immutable records.
- Every mutation emits an immutable audit event with actor, tenant scope, target identifiers, action, and metadata.

## Playbook model (#21)

A `legal_playbook` represents a named policy for one agreement family. A `playbook_version` belongs to a playbook and has a monotonically increasing version number plus `draft` or `published` status. Only one version is published at a time for a playbook. A new draft is copied from the selected source version; publication atomically freezes its rule content.

Each `playbook_rule` belongs to a version and contains:

- `clause_type` and a human-readable title;
- a policy type: `required`, `prohibited`, or `preferred`;
- `preferred_language` and optional approved `fallback_language`;
- `severity` (`low`, `medium`, `high`, or `critical`);
- legal rationale and reviewer guidance;
- an evaluation configuration that distinguishes deterministic matching from a permitted semantic assessment.

Draft rules are editable and deletable after explicit confirmation. Publication validates unique clause types, mandatory policy fields, valid severity, and requires preferred/fallback language where the policy type needs it. Published rows are protected both by service-layer authorization and database-aware immutable-state checks.

## Findings and evaluation (#23–#25)

Running a review selects a published playbook version for an already analysed agreement. It produces a versioned `playbook_evaluation` and one or more immutable `playbook_finding` records. Each finding stores:

- the playbook version, extraction version, and analysis version;
- clause or rule identifier, result (`satisfied`, `missing`, `non_compliant`, or `needs_review`), evaluation method, confidence, and cited evidence;
- policy-derived severity, rationale, reviewer guidance, and review state;
- optional AI explanation and suggestion metadata.

Deterministic checks run first. Semantic model assistance is bounded to ambiguous text and cannot invent compliance, change policy severity, or create fallback policy. Missing or low-confidence evidence becomes `needs_review`. Suggestions only reuse an approved rule’s preferred/fallback language; when no approved language exists, the result recommends review rather than fabricating policy.

## Review workspace (#26)

The agreement review page is extended with a clause-centric workspace:

- document outline and source viewer;
- findings ordered by severity, with status/severity filters;
- synchronized selection among a finding, rule, clause, citation, and highlighted source location;
- source evidence, policy rationale, reviewer guidance, and clearly marked AI-generated suggestion;
- accessible keyboard navigation and explicit loading, empty, failure, and low-confidence states.

The workspace reads persisted artifacts only. It never treats model prose as a policy authority.

## Human decisions and export (#27)

A decision is an append-only event against a finding. It records actor, timestamp, action (`accepted`, `rejected`, or `edited`), the original AI/evaluation result, reviewer rationale, and edited values where applicable. Current finding state is reconstructed from its events; earlier decisions are not overwritten.

Export creates a downloadable cited review report containing agreement identity, selected playbook and immutable version, findings, decisions, source citations, and generation metadata. Exports do not disclose another tenant’s data.

## API contracts

The API uses the existing organization/workspace query scope and OIDC-backed identity path. The contract is introduced in layers:

- CRUD and publication endpoints for draft playbooks and versions;
- read-only published-playbook selection for an agreement;
- create/read evaluation and findings endpoints;
- create/read decision endpoints and a report-export endpoint.

All writes use an idempotency key where the existing API pattern supports replay safety. Mutations validate scope and permissions before any database or object-store action. The OpenAPI schema names each response model so the web client can be generated or typed against stable contracts.

## Error handling and operational behavior

- Cross-tenant or unauthorized reads return the existing non-disclosing access behavior.
- Invalid drafts return field-level validation errors and remain editable.
- A second publish attempt is rejected without changing the published record.
- A review run requires a completed document analysis and a published playbook matching the agreement family.
- Job failures and model unavailability produce explicit, persisted review states; no incomplete result is labelled compliant.
- Audit failures fail closed for sensitive policy and decision mutations.

## Verification

Only the highest-value automated checks are added:

- published playbook immutability and platform-admin-only management;
- deterministic outcomes for satisfied, missing, non-compliant, and ambiguous clauses;
- severity is always derived from playbook policy;
- suggestions are absent when approved language is absent;
- append-only reviewer decision history and cited report contents;
- Playwright workflows for administrator publication, reviewer workspace navigation/filtering, and decision/export.

Every PR runs the existing source checks. UI changes also run the relevant Playwright scenario against `make stack-up`; the final Sprint 3 integration pass runs the complete critical browser journey.

## Non-goals

- Automatically applying suggested language to the source agreement.
- Allowing an LLM to create or alter legal policy.
- OCR expansion, retrieval/Q&A, agreement version comparison, and multi-stage approval orchestration; those remain in later sprints.
