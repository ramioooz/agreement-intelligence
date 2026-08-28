# Responsible AI and human review

Agreement Intelligence assists evidence review; it does not provide legal advice, make a
binding decision, or replace the original agreement and a qualified human reviewer.

## Contents

- [Purpose and decision boundary](#purpose-and-decision-boundary)
- [Operating modes](#operating-modes)
- [Evidence and prompt-injection controls](#evidence-and-prompt-injection-controls)
- [Human review workflow](#human-review-workflow)
- [Evaluation and provenance](#evaluation-and-provenance)
- [Privacy and provider responsibility](#privacy-and-provider-responsibility)
- [Known limitations](#known-limitations)
- [Safe use checklist](#safe-use-checklist)

## Purpose and decision boundary

The product helps a reviewer locate clauses, inspect cited summaries and risks, apply a
versioned legal playbook, compare agreement versions, search authorized text, ask grounded
questions, route review stages, and preserve an audit trail. These functions organize
evidence and workflow; they do not determine whether a contract should be signed.

Model-assisted output is a proposal. Deterministic validation, the original source,
current playbook/policy, and a named reviewer remain authoritative. Approval stages record
human decisions and deny prohibited self-approval; they do not accept a model result as a
decision.

[Back to contents](#contents)

## Operating modes

| Mode | Available | Explicitly unavailable or degraded |
| --- | --- | --- |
| Provider-powered | Deterministic parsing/rules plus provider enrichment, embeddings, semantic retrieval, and grounded answer generation when validated | Nothing is guaranteed if the provider rejects, times out, exceeds quota, or returns invalid evidence |
| No provider key | Repository, deterministic parsing/analysis, workflow, versioning, playbooks, lexical search | Embeddings, semantic retrieval, and provider-generated answers are unavailable |
| Provider outage | Existing deterministic and lexical behavior; new query embeddings retry on later queries | New provider work fails visibly; historical failed enrichment is not automatically backfilled |

No-key behavior is a supported degraded mode, not a simulation of provider quality. A
lexical match is not described as a semantic result, and an unavailable answer is not
replaced by plausible text.

[Back to contents](#contents)

## Evidence and prompt-injection controls

Documents are untrusted evidence. A clause that says “ignore previous instructions” is
agreement content, not a system command. The retrieval and generation path:

1. applies organization/workspace authorization before selecting chunks;
2. labels source content as untrusted evidence;
3. uses versioned model, prompt, schema, embedding, and configuration identifiers;
4. requires typed structured provider output;
5. resolves citations against accessible source anchors and current versions;
6. rejects unsupported or conflicting claims instead of silently completing them;
7. removes historical evidence that the current principal cannot access; and
8. preserves deterministic output when provider-assisted output fails validation.

Citation presence is not proof that a conclusion is correct. A reviewer must open the
cited page/anchor, read surrounding context, confirm the correct version, and compare the
claim with the source language.

[Back to contents](#contents)

## Human review workflow

- Platform administrators configure versioned playbooks and approval policies.
- Legal reviewers inspect findings, evidence, preferred positions, uncertainty, and
  comparison alignment; their role also has business-user upload/update permissions in
  the seeded local demo.
- Business approvers act only on eligible assigned stages and can read the relevant
  agreement evidence.
- The workflow separates reviewer decisions from approval decisions, records comments and
  assignments, denies unauthorized or self-approval paths, and creates immutable terminal
  packages with checksums.
- Requesting changes produces a workflow state that requires human resolution; it is not
  an automatic rewrite or negotiation.

The original agreement and qualified reviewer judgment take precedence over any summary,
risk score, materiality label, alignment, or generated answer.

[Back to contents](#contents)

## Evaluation and provenance

The deterministic release gate measures frozen classification, extraction, retrieval,
grounding, citation, comparison, and safety cases without a provider key. Provider-assisted
evaluation is opt-in, records provider/model/configuration, aggregate latency, usage/cost,
and validation outcome, and is not made a flaky gate when the external service varies.

Artifacts preserve safe provenance such as model, endpoint kind, configuration and schema
versions, timing, token/cost totals, retry/fallback outcome, embedding dimensions/index
version, and reason codes. They must not preserve raw prompts, provider bodies, agreement
text, credentials, personal emails, or tokens.

Evaluation datasets are synthetic or legally reusable. A passing frozen set demonstrates
regression control for those cases; it does not establish legal correctness across every
agreement family, language, jurisdiction, drafting style, or adversarial input.

See [unified quality](../evaluation/unified-quality.md),
[retrieval quality](../evaluation/retrieval-quality.md), and
[version-comparison baseline](../evaluation/version-comparison-baseline.md).

[Back to contents](#contents)

## Privacy and provider responsibility

The operator decides whether a document may be sent to the configured model or embedding
provider. Before enabling a provider, verify the provider agreement, data-use/retention
settings, processing region, subprocessor terms, access controls, budget, and incident
process. Do not use a personal key for regulated or confidential agreements.

The key stays in ignored local configuration. Never place it in a shell command recorded
in history, screenshot, Insomnia export, trace, log, evaluation report, or pull request.
The application redacts telemetry at its own boundary, but the operator remains
responsible for provider-side logging and retention.

Embeddings can disclose characteristics of source text and inherit the source document's
tenant, access, retention, backup, and deletion boundary.

[Back to contents](#contents)

## Known limitations

- Only the implemented agreement families and frozen evaluation cases have measured local
  evidence; coverage is not universal.
- Scanned or image-only documents may produce `ocr_required`; no OCR engine/provider is
  bundled.
- Provider output can be incomplete, biased, stale, inconsistent, expensive, or
  unavailable even after validation.
- Lexical fallback preserves textual search, not semantic equivalence.
- New queries can retry embeddings after recovery, but complete automatic historical
  re-enrichment/backfill is deferred.
- Materiality and clause alignment are decision support, not binding legal conclusions.
- The UI does not prove accessibility conformance; the manual guide covers basic keyboard,
  focus, labeling, responsive, and error-state checks.
- LocalStack and Docker do not validate live AWS privacy, security, resilience, cost, or
  identity-federation behavior.

[Back to contents](#contents)

## Safe use checklist

Before relying on an output:

- [ ] Confirm the organization, workspace, agreement, and version.
- [ ] Open every material citation in the original document.
- [ ] Read context around extracted text; do not rely on snippets alone.
- [ ] Distinguish deterministic, lexical, semantic, and provider-generated states.
- [ ] Investigate `unavailable`, `insufficient_evidence`, `conflicting_evidence`,
      `ocr_required`, failure, and unresolved-alignment states.
- [ ] Record a qualified human rationale for legal and approval decisions.
- [ ] Check that the applicable playbook and approval policy versions are published and
      current.
- [ ] Avoid entering personal data, credentials, or confidential text in free-form notes.
- [ ] Escalate suspected cross-tenant access, ungrounded claims, or leaked secrets through
      the [security policy](../../SECURITY.md).
- [ ] Preserve only non-sensitive evidence needed for audit and defect reproduction.

See the [manual QA and API guide](../testing/manual-test-plan.md) for executable positive,
negative, security, provider-outage, and cross-tenant cases.

[Back to top](#responsible-ai-and-human-review)
