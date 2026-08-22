# Local AI Platform Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI behavior reproducible, regression-tested, observable, and bounded by tenant-aware usage controls in the local release.

**Architecture:** PostgreSQL stores immutable approved configuration and evaluation records; the worker gateway resolves those versions for generation, embeddings, and Q&A. OpenTelemetry carries privacy-filtered operational signals through the Collector, and Redis enforces ephemeral distributed limits without becoming durable workflow state.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PostgreSQL, worker model gateway, Promptfoo, Ragas, frozen JSON datasets, OpenTelemetry Collector, Langfuse local observability profile, Redis, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-22-local-public-release-design.md`

## Global Constraints

- Merge the shared privacy controls from the release-blocker plan before telemetry work.
- Prompt templates, schemas, routes, and parameters are immutable after publication.
- Langfuse may mirror approved identifiers and safe spans; it is not the configuration source of truth.
- Frozen project datasets and deterministic graders remain the release authority.
- Model-assisted quality reports are scheduled or opt-in and do not create flaky PR gates.
- Redis keys always include organization/workspace scope and never contain document text.

---

### Task 1: Add the immutable AI configuration registry (#45)

**Files:**
- Create: `apps/api/migrations/versions/20260822_0030_ai_configuration_registry.py`
- Create: `apps/api/src/agreement_intelligence_api/ai_config/__init__.py`
- Create: `apps/api/src/agreement_intelligence_api/ai_config/models.py`
- Create: `apps/api/src/agreement_intelligence_api/ai_config/schemas.py`
- Create: `apps/api/src/agreement_intelligence_api/ai_config/service.py`
- Create: `apps/api/src/agreement_intelligence_api/ai_config/routes.py`
- Create: `apps/api/tests/test_ai_configuration.py`
- Create: `apps/worker/src/agreement_intelligence_worker/ai_configuration.py`
- Create: `apps/worker/tests/test_ai_configuration.py`
- Modify: `apps/api/src/agreement_intelligence_api/main.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/model_gateway.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/analysis_provider.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/embedding_indexing.py`
- Modify: `apps/api/src/agreement_intelligence_api/qa/service.py`

**Interfaces:**
- Produces: immutable `AIConfigurationVersion` records for `document_analysis`, `embedding`, `grounded_qa`, and `version_materiality`
- Produces: `resolve_configuration(operation: AIOperation, environment: str) -> ResolvedAIConfiguration`
- Consumes: approved prompt template, structured schema, model route, parameters, and promotion state

- [ ] **Step 1: Write registry behavior tests**

Test draft creation, publication immutability, duplicate version rejection, environment promotion by version ID, unauthorized publication, and historical resolution after a new version is promoted.

- [ ] **Step 2: Confirm the tests fail**

```bash
uv run pytest apps/api/tests/test_ai_configuration.py apps/worker/tests/test_ai_configuration.py -v
```

Expected: import/collection failure because the registry modules do not exist.

- [ ] **Step 3: Add the registry migration and domain**

Persist operation, semantic version, prompt content checksum, schema JSON/checksum, model route, parameters JSON, status (`draft`, `published`, `retired`), creator, timestamps, and immutable promotion records. Published rows reject update/delete at the service and database-trigger boundary.

- [ ] **Step 4: Add authorized administration APIs**

Expose create, validate, publish, promote, list, and read endpoints under `/ai-configurations`. Require an existing administrative permission and audit every publication/promotion using only checksums and version identifiers.

- [ ] **Step 5: Add worker resolution**

Define:

```python
@dataclass(frozen=True)
class ResolvedAIConfiguration:
    operation: str
    version: str
    prompt_template: str
    schema: Mapping[str, object]
    model_route: str
    parameters: Mapping[str, object]
```

The resolver reads the promoted immutable version, falls back to an explicitly versioned built-in configuration when no database promotion exists, and includes the resolved version in `GatewayProvenance`.

- [ ] **Step 6: Use the resolver at every model boundary**

Document analysis, embeddings, grounded Q&A, and materiality calls must record configuration version, schema checksum, and route. Historical artifacts keep their original values.

- [ ] **Step 7: Verify**

```bash
uv run pytest apps/api/tests/test_ai_configuration.py apps/worker/tests/test_ai_configuration.py apps/worker/tests/test_model_gateway.py apps/api/tests/test_grounded_qa.py -v
make check
```

- [ ] **Step 8: Commit**

```bash
git add apps/api apps/worker
git commit -m "feat: add immutable AI configuration registry"
```

### Task 2: Build the unified evaluation gate (#46)

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/unified_evaluation.py`
- Create: `apps/worker/tests/golden/unified/v1/manifest.json`
- Create: `apps/worker/tests/golden/unified/v1/accepted-baseline.json`
- Create: `apps/worker/tests/test_unified_evaluation.py`
- Create: `evals/promptfoo.yaml`
- Create: `evals/ragas.py`
- Create: `docs/evaluation/unified-quality.md`
- Modify: `Makefile`
- Modify: `package.json`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/ci/test-ci-workflow.sh`

**Interfaces:**
- Produces: `EvaluationReport` with per-capability metrics, baseline deltas, changed cases, latency, token, and cost summaries
- Consumes: frozen classification, extraction, retrieval, grounding, comparison, and guardrail datasets

- [ ] **Step 1: Write deterministic gate tests**

Test accepted baseline loading, refusal to overwrite the baseline, threshold regression failure, readable changed-case output, and zero unauthorized/unsupported/citation violations.

- [ ] **Step 2: Confirm failure**

```bash
uv run pytest apps/worker/tests/test_unified_evaluation.py -v
```

- [ ] **Step 3: Implement the deterministic harness**

Expose:

```python
def evaluate_release(
    manifest_path: Path,
    baseline_path: Path,
    results_path: Path,
) -> EvaluationReport:
    ...
```

Fail when unauthorized retrieval is non-zero, citation precision is below 1.0, unsupported accepted claims are non-zero, comparison critical recall is below 1.0, or retrieval recall@5 drops more than 0.05 from the accepted baseline.

- [ ] **Step 4: Add prompt and RAG auxiliary suites**

Install Promptfoo and Ragas through exact lockfile updates. Promptfoo covers injection/refusal/schema regressions using synthetic inputs. Ragas reads an explicit results file and produces a model-assisted report; it does not update accepted baselines.

- [ ] **Step 5: Add commands and CI artifacts**

Add `make ai-eval` for deterministic gating and `make ai-eval-assisted` for opt-in provider evaluation. CI runs only `make ai-eval` and uploads the JSON/Markdown report even on a threshold failure.

- [ ] **Step 6: Verify**

```bash
make ai-eval
uv run pytest apps/worker/tests/test_unified_evaluation.py -v
tests/ci/test-ci-workflow.sh
make check
```

Expected: deterministic gates pass and the accepted baseline file remains byte-for-byte unchanged.

- [ ] **Step 7: Commit**

```bash
git add apps/worker evals docs/evaluation Makefile package.json pnpm-lock.yaml pyproject.toml uv.lock .github/workflows/ci.yml tests/ci/test-ci-workflow.sh
git commit -m "feat: add unified AI quality gate"
```

### Task 3: Add safe end-to-end observability (#47)

**Files:**
- Create: `packages/platform-core/src/agreement_intelligence_platform/observability.py`
- Create: `packages/platform-core/tests/test_observability.py`
- Create: `compose.observability.yaml`
- Create: `docker/langfuse/.env.example`
- Create: `docs/operations/observability.md`
- Modify: `docker/otel/collector.yaml`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `apps/api/src/agreement_intelligence_api/main.py`
- Modify: `apps/api/src/agreement_intelligence_api/middleware.py`
- Modify: `apps/api/src/agreement_intelligence_api/processing/queue.py`
- Modify: `apps/api/src/agreement_intelligence_api/search/service.py`
- Modify: `apps/api/src/agreement_intelligence_api/qa/service.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/main.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/processing.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/model_gateway.py`
- Modify: `apps/mcp/src/agreement_intelligence_mcp/app.py`
- Test: `apps/api/tests/test_telemetry.py`
- Test: `apps/worker/tests/test_processing.py`
- Test: `tests/stack/test-compose-contract.sh`

**Interfaces:**
- Produces: W3C trace propagation helpers, low-cardinality metric names, and safe span attributes
- Consumes: correlation ID, tenant-safe opaque IDs, operation status, latency, retry counts, token/cost totals, and evaluation outcomes

- [ ] **Step 1: Add propagation and redaction tests**

Prove one synthetic `traceparent` flows API request → outbox/queue message → worker processing → retrieval/model span, while prohibited values are absent from exported attributes.

- [ ] **Step 2: Implement shared observability helpers**

Provide:

```python
def inject_trace_context(headers: MutableMapping[str, str]) -> None: ...
def extract_trace_context(headers: Mapping[str, str]) -> Context: ...
def metric_attributes(operation: str, outcome: str) -> dict[str, str]: ...
```

All attributes pass through the shared privacy package before export.

- [ ] **Step 3: Instrument critical operations**

Instrument web/API request correlation, API database operations, outbox/queue publish, queue age and receive, worker retries, parsing, retrieval, model gateway, evaluation, workflow transition, and MCP tool execution. Do not use email, subject, workspace name, agreement title, raw UUID lists, or document text as metric labels.

- [ ] **Step 4: Add the local observability profile**

Keep the default stack lightweight. `compose.observability.yaml` adds self-hosted Langfuse and its pinned dependencies under the same Compose project. The Collector exports OTLP data to that profile when enabled and retains the debug exporter for diagnosis.

- [ ] **Step 5: Document startup and evidence**

Add commands to start the base stack plus observability override, find a correlation/trace ID, inspect latency/tokens/cost/retrieval spans, and verify redaction. State that Langfuse mirrors safe telemetry and is not the prompt/configuration authority.

- [ ] **Step 6: Verify**

```bash
uv run pytest packages/platform-core/tests/test_observability.py apps/api/tests/test_telemetry.py apps/worker/tests/test_processing.py -v
tests/stack/test-compose-contract.sh
make check
```

Run one local upload-to-analysis trace and record its opaque trace ID without source content.

- [ ] **Step 7: Commit**

```bash
git add packages/platform-core apps/api apps/worker apps/mcp compose.yaml compose.observability.yaml docker docs/operations .env.example tests/stack
git commit -m "feat: add privacy-safe platform observability"
```

### Task 4: Enforce quotas, limits, and cost controls (#50)

**Files:**
- Create: `apps/api/src/agreement_intelligence_api/limits.py`
- Create: `apps/api/src/agreement_intelligence_api/usage.py`
- Create: `apps/api/tests/test_limits.py`
- Create: `apps/api/migrations/versions/20260822_0031_ai_usage_ledger.py`
- Modify: `apps/api/src/agreement_intelligence_api/redis_client.py`
- Modify: `apps/api/src/agreement_intelligence_api/middleware.py`
- Modify: `apps/api/src/agreement_intelligence_api/analysis/service.py`
- Modify: `apps/api/src/agreement_intelligence_api/search/routes.py`
- Modify: `apps/api/src/agreement_intelligence_api/qa/routes.py`
- Modify: `apps/api/src/agreement_intelligence_api/processing/service.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/model_gateway.py`
- Modify: `.env.example`
- Modify: `compose.yaml`
- Test: `apps/api/tests/test_redis_client.py`
- Test: `apps/worker/tests/test_model_gateway.py`

**Interfaces:**
- Produces: `LimitDecision(allowed, reason, retry_after_seconds, reservation_id)`
- Produces: `reserve_usage(scope, operation, estimated_tokens, estimated_cost) -> LimitDecision` and `settle_usage(reservation_id, actual_usage) -> None`
- Consumes: organization/workspace/user scope, endpoint/job type, model operation, and safe usage provenance

- [ ] **Step 1: Write isolation and retry tests**

Cover per-tenant and per-user windows, concurrent Redis increments, budget reservation, settlement, duplicate settlement, Redis unavailability, retry-after response, and absence of another tenant’s usage values.

- [ ] **Step 2: Confirm focused failures**

```bash
uv run pytest apps/api/tests/test_limits.py apps/api/tests/test_redis_client.py -v
```

- [ ] **Step 3: Implement atomic Redis limits**

Use a Lua script to increment and expire counters atomically. Keys use opaque organization/workspace/user IDs and operation names. A Redis outage fails closed for expensive provider operations and uses a documented conservative in-process limit only for low-cost reads.

- [ ] **Step 4: Add the durable usage ledger**

Persist reservation ID, tenant scope, operation, configuration version, estimated/actual tokens and cost, status, and timestamps. Unique reservation and settlement keys make retries idempotent.

- [ ] **Step 5: Wire API and worker checks**

Apply request-rate limits at middleware/routes, reserve budget before queuing or model calls, and settle from `GatewayProvenance`. Return HTTP 429 with `Retry-After` for rate limits and a typed budget-exhausted response without exposing numeric usage from another tenant.

- [ ] **Step 6: Verify**

```bash
uv run pytest apps/api/tests/test_limits.py apps/api/tests/test_redis_client.py apps/api/tests/test_grounded_qa.py apps/api/tests/test_processing_jobs.py apps/worker/tests/test_model_gateway.py -v
make check
```

- [ ] **Step 7: Commit**

```bash
git add apps/api apps/worker .env.example compose.yaml
git commit -m "feat: enforce tenant usage controls"
```
