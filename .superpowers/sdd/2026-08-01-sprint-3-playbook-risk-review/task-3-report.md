# Story #23 — Playbook Evaluation Report

## Delivered

- Added scoped `playbook_evaluations` and `playbook_findings` persistence with PostgreSQL RLS policies, agreement/playbook provenance, analysis and extraction versions, citations, confidence, evaluation method, severity, and review state.
- Added `POST` and `GET /agreements/{agreement_id}/playbook-evaluations`. Submission is restricted to review-capable principals, validates the agreement scope, requires a completed analysis artifact, requires a published playbook version in the same scope and agreement family, and persists the deterministic findings read from the immutable analysis artifact.
- Added deterministic worker rule evaluation with fixtures covering grounded required compliance, absent extraction evidence, prohibited text, and low-confidence evidence. Absent/low-confidence evidence always produces `needs_review`; deterministic checks precede the bounded semantic extension point, which cannot manufacture a satisfied result.
- Extended document processing with an optional evaluation sink that is called only after the immutable analysis artifact is written, allowing selected published same-family evaluation persistence to be composed into worker processing without treating an incomplete analysis as compliant.

## Files

- API review domain: `apps/api/src/agreement_intelligence_api/reviews/{models,schemas,service,routes,__init__}.py`
- API integration/migration: `apps/api/src/agreement_intelligence_api/main.py`, `apps/api/migrations/versions/20260801_0009_playbook_evaluations.py`
- Worker evaluation/integration: `apps/worker/src/agreement_intelligence_worker/playbook_evaluation.py`, `apps/worker/src/agreement_intelligence_worker/document_processor.py`
- Tests: `apps/api/tests/test_review_evaluations.py`, `apps/worker/tests/test_playbook_evaluation.py`, `apps/worker/tests/test_document_processor.py`

## Acceptance Evidence

- Worker fixtures verify satisfied, absent-evidence/needs-review, prohibited/non-compliant, and low-confidence/needs-review outcomes with cited provenance.
- API integration coverage verifies persisted findings include the selected published version, analysis/extraction provenance, rule-derived severity, deterministic method, citation IDs, and scoped readback; mismatched agreement family is rejected.
- Fresh `make check` completed successfully: formatting, linting, type checks, 28 web tests, 139 Python tests passed, package builds, and CI/auth contract scripts passed. One existing optional PostgreSQL RLS integration test was skipped because `AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL` was not configured.

## Commit and Push

- Commit: `a97700f3b2217f4d59d10be894a49d2624e7128c` (`feat: evaluate agreements against playbooks`)
- Branch: `feat/playbook-evaluation`
- Push: `origin/feat/playbook-evaluation` completed successfully after the implementation and report commits.

## Concerns

- Semantic assessment is deliberately an injected, explicitly configured extension point; no model provider is wired for it in this story, so all current persisted API findings use deterministic evaluation.

## Review Fix Round 1

- Corrected both API and worker deterministic paths so a prohibited rule with no configured policy text is persisted as `needs_review`, never `satisfied`.
- Corrected semantic assessment to receive the same selected highest-confidence candidate whose citation, confidence, and extraction provenance are persisted.
- Added and composed `SQLAlchemyPlaybookEvaluationSink` in the production worker runtime. It sets PostgreSQL tenant scope, selects a published same-family playbook in the job's organization/workspace, evaluates the immutable manifest, and persists scoped evaluations/findings.
- Focused regression evidence: `17 passed` across the API/worker review, sink, and document-processor tests. A fresh full `make check` then passed with `143 passed, 1 skipped` Python tests, 28 web tests, static checks, contract scripts, and both package builds.

## Review Fix Round 2

- Moved review evaluation from document parsing to a `JobProcessor` post-completion handler. The immutable artifact and completed job state are now durably persisted before the worker reads the artifact and writes any evaluation/finding rows.
- Wired the production runtime with the shared object storage and post-completion SQLAlchemy handler; document parsing no longer writes review data directly.
- Added lifecycle regressions proving evaluation observes `completed` state, is skipped on redelivery, and is not called when durable completion raises. This prevents completion failures from leaving review findings behind.
- Focused regression evidence: `18 passed`; a fresh `make check` then passed with `144 passed, 1 skipped` Python tests, 28 web tests, static checks, contract scripts, and both package builds.

## Review Fix Round 3

- Added completed-artifact recovery to `JobProcessor`: redelivery of a durable completed job invokes the post-completion handler with the persisted artifact instead of silently acknowledging it.
- Added `processing_job_id` and a unique job/version constraint to evaluation persistence. The worker sink checks that idempotency key before writing, so recovery cannot duplicate findings.
- Added regressions for transient handler failure followed by redelivery success, repeated completed-artifact recovery after durable completion, and idempotent sink re-entry.
- Focused regression evidence: `3 passed`; a fresh `make check` then passed with `145 passed, 1 skipped` Python tests, 28 web tests, static checks, contract scripts, and both package builds.
