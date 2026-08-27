# Roadmap, limitations, and room for improvement

This roadmap separates implemented behavior from useful future work. It is not a promise,
schedule, or claim that deferred capabilities exist.

## Current release boundary

The current repository delivers the complete local repository, processing, playbook,
retrieval/Q&A, comparison, review/approval, audit/package, MCP, evaluation, security, and
operations workflows described in the root [README](../README.md). A user-supplied
provider key unlocks validated model/embedding behavior; no-key mode remains deterministic
and lexical with explicit unavailable states.

The local release is not a live cloud deployment. The owner must complete manual QA and
decide repository visibility.

## Near-term product and AI improvements

- **Automatic provider-recovery enrichment backfill:** reconcile historical documents that
  completed while model or embedding services were unavailable. Current recovery is
  authorized manual retry/requeue/reprocessing; automatic backfill remains deferred.
- **OCR integration:** connect an approved, resource-bounded OCR engine/provider to the
  existing `ocr_required` diagnostic while preserving tenant, privacy, citation, and cost
  controls. No OCR engine is currently bundled.
- **Additional provider adapters:** add maintained Anthropic/Gemini or other approved
  typed adapters only with equivalent configuration governance, evidence validation,
  privacy, evaluation, fallback, and cost behavior. They are not runtime dependencies now.
- **Broader agreement families:** label legally reusable datasets and add domain playbooks,
  schemas, extraction/evaluation cases for Prime Broker, IB, ISDA, regulatory, and other
  documents rather than assuming current family quality transfers.
- **Multilingual evaluation:** measure parsing, retrieval, citations, legal terminology,
  and refusal behavior before declaring language support.
- **Richer uncertainty calibration:** improve reviewer-facing explanations and compare
  calibrated uncertainty with human adjudication; avoid false precision.
- **Controlled redlining/drafting assistance:** any future generation must remain
  suggestion-only, evidence-linked, versioned, and human-approved.

## User experience and accessibility

- Expand automated accessibility coverage beyond current component checks and manual
  keyboard/focus/label/error cases.
- Validate stable Chrome, Firefox, Safari, and Edge behavior in a maintained compatibility
  matrix; current automated E2E is Chromium.
- Add clearer job timelines, bulk-safe operations, saved searches, notification controls,
  and recovery guidance without exposing tenant information.
- Improve responsive layouts for comparison and evidence-heavy review screens after
  measured browser testing.
- Add user-facing export/redaction choices only with an explicit retention and audit model.

## Operations and platform

- Add autonomous, observable reconciliation for any remaining recovery path that requires
  traffic or operator action.
- Run sustained soak, larger concurrency, storage growth, and cost tests with synthetic
  data and explicit capacity budgets.
- Add managed retention enforcement, legal-hold policy, deletion reporting, and backup
  lifecycle appropriate to the deploying organization.
- Add signed release artifacts, SBOM publication, image provenance/attestation, and a
  maintained vulnerability disclosure/release process.
- Automate supported-version and changelog management after tagged releases begin.

## Deferred live AWS work

An owner-authorized environment is required to apply and validate the cloud reference:

- real IAM evaluation, VPC/subnet/security-group paths, DNS, certificates, TLS, ALB, WAF;
- ECS service/task behavior, RDS/pgvector operations, managed Redis, S3/SQS semantics,
  Secrets Manager rotation, image registry and deployment rollback;
- autoscaling, alarms, dashboards, cost/load limits, network failure, and regional behavior;
- managed backup/restore, destructive recovery, RPO/RTO, and disaster-recovery exercises;
- Cognito and Microsoft Entra federation, account lifecycle, group mapping, and enterprise
  single sign-out; and
- cloud security posture, penetration testing, data residency, and operational readiness.

LocalStack is retained for local parity and Terraform contract checks. It cannot prove any
item above.

## Explicit non-goals for the initial release

- Claiming legal advice, autonomous approval, or universal agreement understanding.
- Claiming real OCR when only `ocr_required` exists.
- Treating lexical results as semantic results or unavailable provider output as success.
- Bundling provider credentials, model weights, real agreements, or personal data.
- Adding another queue, vector database, orchestration framework, or AI framework only for
  portfolio visibility.
- Changing repository visibility, deploying to AWS, or creating cloud spend automatically.

## How to evaluate a roadmap proposal

A proposal should identify the user outcome, source of truth, tenant/privacy impact,
provider/cloud dependency, failure and recovery state, evaluation evidence, operational
cost, and migration/rollback plan. Changes to authentication, authorization, persistence,
messaging, externally visible APIs, or security posture require an ADR.

See [Contributing](../CONTRIBUTING.md), [Threat model](security/threat-model.md), and
[Responsible AI](security/responsible-ai.md).

[Back to top](#roadmap-limitations-and-room-for-improvement)
