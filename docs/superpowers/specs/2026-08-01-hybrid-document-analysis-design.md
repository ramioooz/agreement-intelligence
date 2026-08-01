# Hybrid document analysis design

## Goal

Augment deterministic document understanding with an optional LLM interpretation
layer. The product continues to parse source documents and create stable citation
anchors locally; the LLM contributes agreement classification, clause and risk
findings, and business and legal summaries.

## Scope

- Analyze only canonical extracted document blocks, never browser-session data.
- Return structured classification, clauses, risks, and summaries in a versioned
  artifact contract.
- Require one or more existing citation-anchor IDs for every substantive finding.
- Validate model output before publishing it. Invalid output, provider errors,
  timeouts, and missing configuration fall back to deterministic artifacts.
- Display analysis provenance, risks, citations, and fallback diagnostics in the
  existing Document understanding experience.

## Architecture

The worker owns provider calls. It receives the canonical document model created
by the parser, gives the provider a bounded representation of its blocks and
anchor IDs, then validates the structured response against the artifact schema.

The provider interface is separate from the processor. A configured hosted
provider implements it; a deterministic implementation remains the default when
the key is unavailable. This allows model replacement without changing API or UI
contracts.

```text
source document
  -> parser and citation anchors
  -> deterministic baseline
  -> optional provider interpretation
  -> evidence and schema validation
  -> versioned analysis artifact
  -> API and Document understanding UI
```

## Data contract and validation

The provider response contains:

- classification: family, confidence, rationale, evidence anchors;
- clauses: taxonomy category, normalized fields, source excerpt, confidence,
  evidence anchors;
- risks: severity, explanation, affected clause/category, evidence anchors;
- summaries: business and legal claims, each with evidence anchors;
- provenance: provider, model, prompt/schema version, latency, token usage, and
  fallback reason when applicable.

Validation rejects unknown anchor IDs, absent evidence, duplicate or invalid
categories, malformed structured output, and over-sized responses. Rejected
provider output never replaces the deterministic artifact.

## Configuration and security

`OPENAI_API_KEY` and `OPENAI_MODEL` are worker-only runtime settings. The local
key is stored in the ignored `.env`; production uses AWS Secrets Manager. The
key is excluded from source control, browser code, normal logs, test fixtures,
and artifacts. Provider requests and responses are not written to ordinary logs;
only safe operational metadata is retained.

When no key is configured, processing succeeds with deterministic output and a
diagnostic stating that the provider was unavailable by configuration.

## Failure behavior

Transient provider failures use the existing job retry policy. Permanent errors,
schema validation failures, or absent configuration publish the deterministic
artifact with a diagnostic rather than failing a document review.

## Verification

- Unit tests use a fake provider and prove cited structured output is accepted.
- Tests prove uncited or invalid output is rejected and the deterministic
  fallback remains available.
- An opt-in local smoke command uses the configured key and is excluded from CI.
- Golden agreements compare deterministic and provider-enhanced results for
  classification, clauses, risks, grounded summaries, latency, and usage.
