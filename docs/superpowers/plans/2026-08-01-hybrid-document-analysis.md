# Hybrid Document Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, evidence-grounded LLM interpretation layer that enriches deterministic agreement analysis without making provider access a runtime requirement.

**Architecture:** The worker keeps parsing documents and generating citation anchors locally. It builds a deterministic baseline, then optionally asks a provider for strict structured enrichment over bounded blocks and anchor IDs. A validator accepts only cited, schema-valid output; any disabled provider, timeout, error, or invalid response publishes the deterministic baseline with a safe diagnostic.

**Tech Stack:** Python 3.13, OpenAI Python SDK and Responses API, Pydantic structured output, FastAPI, Next.js 16, TypeScript, PostgreSQL, LocalStack S3/SQS, Docker Compose, pytest, Vitest.

## Global Constraints

- Keep `OPENAI_API_KEY` worker-only; never commit, log, return to the browser, or place it in test fixtures.
- Default model: `gpt-5.4-mini`, configurable through `OPENAI_MODEL`.
- CI uses fake providers only and never performs a hosted provider call.
- Every provider-produced classification, clause, risk, and summary claim requires existing citation-anchor IDs.
- Invalid provider output and provider unavailability must preserve deterministic analysis rather than fail document processing.
- All code changes use a dedicated branch and a ready PR; only the user merges to `main`.
- Do not use assistant, vendor, model-provider, or tool branding in branch names, commit messages, or PR titles.

---

## File Structure

- `apps/worker/src/agreement_intelligence_worker/analysis_provider.py`: provider-neutral request, response, protocol, and runtime configuration.
- `apps/worker/src/agreement_intelligence_worker/analysis_validation.py`: validates provider claims against canonical anchor IDs and normalizes accepted output.
- `apps/worker/src/agreement_intelligence_worker/document_processor.py`: assembles deterministic baseline, optional enrichment, diagnostics, provenance, and manifest.
- `apps/worker/src/agreement_intelligence_worker/main.py`: wires provider configuration into the production worker runtime.
- `apps/worker/src/agreement_intelligence_worker/provider_smoke.py`: explicit local-only provider preflight command.
- `apps/worker/tests/test_analysis_provider.py`: fake-provider configuration and request-contract tests.
- `apps/worker/tests/test_analysis_validation.py`: evidence and malformed-output rejection tests.
- `apps/worker/tests/test_document_processor.py`: processor enrichment and deterministic-fallback tests.
- `apps/web/src/lib/agreement-api.ts`: analysis risk and provenance types.
- `apps/web/src/components/agreement-detail.tsx`: cited risk and provenance rendering.
- `apps/web/src/components/agreement-detail.test.tsx`: UI assertions for risk/provenance states.
- `apps/worker/pyproject.toml`, `uv.lock`: pinned provider SDK dependency.
- `.env.example`, `compose.yaml`, `Makefile`: worker configuration and opt-in smoke command.

## Task 1: Provider boundary and safe configuration

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/analysis_provider.py`
- Create: `apps/worker/tests/test_analysis_provider.py`
- Modify: `apps/worker/pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`
- Modify: `compose.yaml`

**Interfaces:**
- Consumes: canonical `list[tuple[str, str]]` blocks from `DocumentUnderstandingProcessor`.
- Produces: `AnalysisProvider.analyze(blocks: list[tuple[str, str]]) -> ProviderAnalysis` and `provider_from_environment() -> AnalysisProvider | None`.

- [ ] **Step 1: Write the failing configuration and request-contract tests**

```python
def test_provider_is_disabled_without_an_api_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert provider_from_environment() is None


def test_provider_receives_only_anchor_ids_and_extracted_blocks() -> None:
    client = RecordingClient(response=VALID_RESPONSE)
    provider = HostedAnalysisProvider(client=client, model="gpt-5.4-mini")

    provider.analyze([("citation-a", "Termination is permitted on notice.")])

    assert client.requested_anchor_ids == ["citation-a"]
    assert "Termination is permitted" in client.requested_text
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_analysis_provider.py -v`

Expected: FAIL because `analysis_provider` and `provider_from_environment` do not exist.

- [ ] **Step 3: Add the provider SDK and configuration**

Run: `uv add --package agreement-intelligence-worker openai`

Add the worker-only Compose environment entries and ignored-local example entries:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.4-mini
```

Implement this minimal provider contract:

```python
@dataclass(frozen=True)
class ProviderAnalysis:
    classification: dict[str, object]
    clauses: list[dict[str, object]]
    risks: list[dict[str, object]]
    summaries: dict[str, dict[str, object]]
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


class AnalysisProvider(Protocol):
    def analyze(self, blocks: list[tuple[str, str]]) -> ProviderAnalysis: ...


def provider_from_environment() -> AnalysisProvider | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return HostedAnalysisProvider(
        client=OpenAI(api_key=api_key),
        model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
    )
```

Build the provider request from text plus anchor IDs only. Set a bounded block and character limit, request strict JSON output, and do not emit prompt contents or raw responses to logs.

- [ ] **Step 4: Run focused verification**

Run: `uv run pytest apps/worker/tests/test_analysis_provider.py -v && uv run ruff check apps/worker && uv run mypy apps/worker/src apps/worker/tests`

Expected: PASS with no provider network calls.

- [ ] **Step 5: Commit**

```bash
git add apps/worker/pyproject.toml uv.lock .env.example compose.yaml \
  apps/worker/src/agreement_intelligence_worker/analysis_provider.py \
  apps/worker/tests/test_analysis_provider.py
git commit -m "Add analysis provider boundary"
```

## Task 2: Cited structured-output validation

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/analysis_validation.py`
- Create: `apps/worker/tests/test_analysis_validation.py`

**Interfaces:**
- Consumes: `ProviderAnalysis` from Task 1 and `set[str]` of canonical anchors.
- Produces: `validate_provider_analysis(analysis, allowed_anchor_ids) -> ValidatedAnalysis` or `ProviderOutputValidationError`.

- [ ] **Step 1: Write the failing validator tests**

```python
def test_validator_accepts_cited_clause_risk_and_summary() -> None:
    validated = validate_provider_analysis(VALID_RESPONSE, {"citation-a"})
    assert validated.risks[0]["citation_anchor_ids"] == ["citation-a"]


def test_validator_rejects_a_claim_with_an_unknown_anchor() -> None:
    with pytest.raises(ProviderOutputValidationError):
        validate_provider_analysis(UNKNOWN_ANCHOR_RESPONSE, {"citation-a"})
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_analysis_validation.py -v`

Expected: FAIL because the validation module does not exist.

- [ ] **Step 3: Implement the strict response schema and validation**

Define typed structures for `classification`, `clauses`, `risks`, `summaries`, and `provenance`. Reject each of the following before artifact creation:

```python
if not claim.citation_anchor_ids:
    raise ProviderOutputValidationError("All claims require evidence")
if not set(claim.citation_anchor_ids).issubset(allowed_anchor_ids):
    raise ProviderOutputValidationError("Provider referenced an unknown citation anchor")
if not 0.0 <= claim.confidence <= 1.0:
    raise ProviderOutputValidationError("Confidence must be between zero and one")
```

Limit categories to the existing clause taxonomy plus `other_needs_review`, limit risk severity to `low`, `medium`, `high`, and `critical`, and cap strings and collection sizes before writing an artifact.

- [ ] **Step 4: Run focused verification**

Run: `uv run pytest apps/worker/tests/test_analysis_validation.py -v && uv run ruff check apps/worker && uv run mypy apps/worker/src apps/worker/tests`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/worker/src/agreement_intelligence_worker/analysis_validation.py \
  apps/worker/tests/test_analysis_validation.py
git commit -m "Validate cited analysis output"
```

## Task 3: Hybrid processor, artifacts, and fallback

**Files:**
- Modify: `apps/worker/src/agreement_intelligence_worker/document_processor.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/main.py`
- Modify: `apps/worker/tests/test_document_processor.py`

**Interfaces:**
- Consumes: `AnalysisProvider | None` and `ValidatedAnalysis` from Tasks 1–2.
- Produces: an existing `document-analysis.v1` manifest extended with `risks` and `analysis_provenance`.

- [ ] **Step 1: Write the failing processor tests**

```python
def test_processor_publishes_validated_provider_enrichment() -> None:
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=FakeProvider(VALID_RESPONSE))
    manifest = process_manifest(processor, job)
    assert manifest["classification"]["version"] == "provider-hybrid.v1"
    assert manifest["risks"][0]["severity"] == "high"


def test_processor_keeps_deterministic_output_when_provider_fails() -> None:
    processor = DocumentUnderstandingProcessor(storage, analysis_provider=FailingProvider())
    manifest = process_manifest(processor, job)
    assert manifest["classification"]["version"] == "agreement-family-rules.v1"
    assert manifest["diagnostics"][-1]["code"] == "provider_fallback"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `uv run pytest apps/worker/tests/test_document_processor.py -v`

Expected: FAIL because the processor does not accept or publish provider enrichment.

- [ ] **Step 3: Implement deterministic-first enrichment**

Construct the current classification, clauses, and summaries first. Then use this control flow inside `_manifest`:

```python
manifest = deterministic_manifest(parsed, source)
if self._analysis_provider is None:
    manifest["analysis_provenance"] = {"mode": "deterministic", "fallback_reason": "provider_not_configured"}
    return manifest
try:
    enriched = validate_provider_analysis(
        self._analysis_provider.analyze(blocks),
        {anchor_id for anchor_id, _ in blocks},
    )
except (ProviderError, ProviderOutputValidationError):
    manifest["diagnostics"].append({"code": "provider_fallback", "message": "Provider enrichment was unavailable", "page_numbers": []})
    manifest["analysis_provenance"] = {"mode": "deterministic", "fallback_reason": "provider_fallback"}
    return manifest
manifest.update(enriched.artifact_fields())
manifest["analysis_provenance"] = enriched.provenance
return manifest
```

Add only safe provenance: provider kind, configured model, schema/prompt version, elapsed milliseconds, input/output token counts when supplied, and fallback reason. Do not persist raw provider input or output.

Wire `provider_from_environment()` only in `processing_runtime_from_environment()` so no credential reaches API or web containers.

- [ ] **Step 4: Run focused verification**

Run: `uv run pytest apps/worker/tests/test_document_processor.py -v && uv run ruff check apps/worker && uv run mypy apps/worker/src apps/worker/tests`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/worker/src/agreement_intelligence_worker/document_processor.py \
  apps/worker/src/agreement_intelligence_worker/main.py \
  apps/worker/tests/test_document_processor.py
git commit -m "Enrich document analysis safely"
```

## Task 4: Analysis API types and evidence-first UI

**Files:**
- Modify: `apps/web/src/lib/agreement-api.ts`
- Modify: `apps/web/src/components/agreement-detail.tsx`
- Modify: `apps/web/src/components/agreement-detail.test.tsx`

**Interfaces:**
- Consumes: manifest fields `risks` and `analysis_provenance` from Task 3.
- Produces: a Document understanding view that renders cited risks and provenance without exposing credentials or raw provider data.

- [ ] **Step 1: Write the failing UI test**

```tsx
it("shows a cited high risk and analysis provenance", () => {
  render(<AgreementDetail agreement={agreement} analysis={analysisWithRisk} />);
  expect(screen.getByText("High risk")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View source evidence" })).toBeInTheDocument();
  expect(screen.getByText(/gpt-5.4-mini/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pnpm --filter @agreement-intelligence/web test -- agreement-detail.test.tsx`

Expected: FAIL because risk and provenance fields are not represented.

- [ ] **Step 3: Extend types and render bounded UI content**

Add these fields to `DocumentAnalysis`:

```ts
risks: Array<{
  severity: "low" | "medium" | "high" | "critical";
  explanation: string;
  citation_anchor_ids: string[];
}>;
analysis_provenance: {
  mode: "deterministic" | "hybrid";
  model?: string;
  fallback_reason?: string;
};
```

Render risks in severity order, link each to its first validated evidence anchor, and show an explicit deterministic-fallback notice when `fallback_reason` exists. Never render an API key, raw prompt, raw response, or token-by-token content.

- [ ] **Step 4: Run focused verification**

Run: `pnpm --filter @agreement-intelligence/web test -- agreement-detail.test.tsx && pnpm --filter @agreement-intelligence/web typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/agreement-api.ts \
  apps/web/src/components/agreement-detail.tsx \
  apps/web/src/components/agreement-detail.test.tsx
git commit -m "Show cited analysis risks"
```

## Task 5: Opt-in smoke check, evaluation comparison, and final verification

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/provider_smoke.py`
- Modify: `Makefile`
- Modify: `apps/worker/tests/test_evaluation.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `OPENAI_API_KEY`, `OPENAI_MODEL`, fake providers, and golden agreement fixtures.
- Produces: `make provider-smoke` and a baseline report comparing deterministic and hybrid artifacts without a CI provider call.

- [ ] **Step 1: Write the failing smoke-command and evaluation tests**

```python
def test_evaluation_reports_hybrid_mode_without_calling_a_provider() -> None:
    report = evaluate_documents(provider=FakeProvider(VALID_RESPONSE))
    assert report["modes"] == {"deterministic", "hybrid"}
```

```sh
grep -q '^provider-smoke:' Makefile
```

- [ ] **Step 2: Run the focused checks to verify they fail**

Run: `uv run pytest apps/worker/tests/test_evaluation.py -v && grep -q '^provider-smoke:' Makefile`

Expected: the pytest assertion and the Makefile grep fail.

- [ ] **Step 3: Implement the opt-in command and report**

Implement `provider_smoke.py` to exit non-zero with `OPENAI_API_KEY is required for provider smoke checks` when absent. With a key, make one bounded structured request using fixed non-sensitive sample text and print model, latency, usage, and validation status. Add:

```make
provider-smoke:
	uv run python -m agreement_intelligence_worker.provider_smoke
```

Extend the evaluation report to compare the existing golden fixtures with deterministic and fake-hybrid results. Update README setup instructions to say `OPENAI_API_KEY` belongs only in ignored `.env` and that `make provider-smoke` is opt-in.

- [ ] **Step 4: Run final verification**

Run: `make check && make stack-up && make provider-smoke`

Expected: `make check` and `make stack-up` pass. `make provider-smoke` passes only when a local key is configured; it must never run in CI.

- [ ] **Step 5: Commit**

```bash
git add Makefile README.md apps/worker/src/agreement_intelligence_worker/provider_smoke.py \
  apps/worker/tests/test_evaluation.py
git commit -m "Add hybrid analysis evaluation"
```
