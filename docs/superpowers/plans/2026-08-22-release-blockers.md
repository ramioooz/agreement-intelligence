# Public Release Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove locally detectable security and dependency blockers and produce an evidence-backed independent review before public visibility.

**Architecture:** Harden the existing logging, telemetry, model-gateway, evidence-validation, and authorization seams rather than adding a parallel security layer. Security decisions remain deterministic and fail closed; model output and document text never become authorization or policy instructions.

**Tech Stack:** pnpm audit, pip-audit, Python, FastAPI, Next.js, OpenTelemetry, PostgreSQL audit ledger, pytest, Vitest, Playwright, gitleaks.

**Spec:** `docs/superpowers/specs/2026-08-22-local-public-release-design.md`

## Global Constraints

- Complete production dependency remediation before documentation screenshots or final E2E capture.
- Never log raw agreement text, prompts, provider output, credentials, tokens, email addresses, or personal identifiers.
- Treat uploaded documents and retrieved passages as untrusted data.
- Guardrails cannot grant permissions, change playbook policy, or suppress deterministic findings.
- Every code-review finding receives severity and a GitHub issue before a fix begins.

---

### Task 1: Remediate production dependency vulnerabilities

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `package.json`
- Modify: `apps/web/package.json`
- Modify: `pnpm-lock.yaml`
- Modify: `.github/workflows/ci.yml`
- Modify: `CONTRIBUTING.md`
- Test: `tests/ci/test-ci-workflow.sh`

**Interfaces:**
- Consumes: current locked dependency graph
- Produces: reproducible installs whose production graph has no high/critical audit finding

- [ ] **Step 1: Pin the Python audit tool and capture the failing production audits**

Add the Python auditor to the locked development toolchain:

```bash
uv add --dev --exact pip-audit
```

Run:

```bash
pnpm audit --prod --audit-level high
uv run pip-audit
```

Expected before remediation: the JavaScript audit exits non-zero with the currently reported production findings; the Python audit runs from the lockfile and reports its independent result.

- [ ] **Step 2: Prove CI is too permissive**

Add an assertion to `tests/ci/test-ci-workflow.sh` requiring this exact workflow command:

```yaml
run: pnpm audit --prod --audit-level high
```

Run `tests/ci/test-ci-workflow.sh` and expect failure while CI still uses `critical` without `--prod`.

- [ ] **Step 3: Upgrade only affected direct packages**

Use `pnpm why <affected-package>` for every high/critical path, then use exact-version updates for the owning direct packages. Do not add blanket overrides unless the upstream package’s supported range cannot select a fixed transitive version.

- [ ] **Step 4: Strengthen CI and contributor guidance**

Change `.github/workflows/ci.yml` to run the exact production audit command. Update `CONTRIBUTING.md` so dependency and secret checks are described as current gates rather than future work.

- [ ] **Step 5: Verify application compatibility**

Run:

```bash
pnpm install --frozen-lockfile
pnpm audit --prod --audit-level high
pnpm --filter @agreement-intelligence/web test
pnpm --filter @agreement-intelligence/web typecheck
pnpm --filter @agreement-intelligence/web build
tests/ci/test-ci-workflow.sh
```

Expected: all commands exit zero.

- [ ] **Step 6: Commit**

```bash
git add package.json apps/web/package.json pnpm-lock.yaml .github/workflows/ci.yml CONTRIBUTING.md tests/ci/test-ci-workflow.sh
git add pyproject.toml uv.lock
git commit -m "fix: remediate production dependency risks"
```

### Task 2: Centralize privacy classification and redaction (#48)

**Files:**
- Create: `packages/platform-core/pyproject.toml`
- Create: `packages/platform-core/src/agreement_intelligence_platform/__init__.py`
- Create: `packages/platform-core/src/agreement_intelligence_platform/privacy.py`
- Modify: `pyproject.toml`
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/mcp/pyproject.toml`
- Modify: `apps/worker/pyproject.toml`
- Modify: `apps/api/src/agreement_intelligence_api/logging_config.py`
- Modify: `apps/api/src/agreement_intelligence_api/telemetry.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/logging_config.py`
- Modify: `apps/mcp/src/agreement_intelligence_mcp/app.py`
- Test: `packages/platform-core/tests/test_privacy.py`
- Test: `apps/api/tests/test_api_logging.py`
- Test: `apps/api/tests/test_telemetry.py`

**Interfaces:**
- Produces: `DataClass`, `classify_key(key: str) -> DataClass`, `redact_mapping(values: Mapping[str, object]) -> dict[str, object]`, and `safe_event_metadata(values: Mapping[str, object]) -> dict[str, object]`
- Consumes: dictionaries supplied to logs, audit events, spans, model provenance, and MCP audit metadata

- [ ] **Step 1: Write shared redaction tests**

Cover exact, dotted, nested, and mixed-case keys. The test matrix must remove `document.text`, `prompt`, `provider_output`, `authorization`, `access_token`, `api_key`, `password`, `email`, and nested credential objects while retaining identifiers such as correlation ID, status, model configuration version, duration, and token counts.

- [ ] **Step 2: Run the privacy tests before implementation**

Run:

```bash
uv run pytest packages/platform-core/tests/test_privacy.py -v
```

Expected: collection failure because the shared package does not exist.

- [ ] **Step 3: Implement recursive redaction**

Define:

```python
class DataClass(StrEnum):
    PROHIBITED = "prohibited"
    RESTRICTED = "restricted"
    OPERATIONAL = "operational"


def redact_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return _redact_node(values, parent_key="")
```

`_redact_node` must recurse through mappings and sequences, evaluate full dotted paths and leaf keys case-insensitively, replace prohibited values with `"[redacted]"`, and retain only allow-listed restricted metadata.

- [ ] **Step 4: Wire every service to the shared policy**

Replace `_safe_message` and `telemetry.redact_attributes` denylist behavior with the shared package. Apply the same boundary before worker JSON logs and MCP/audit attributes are emitted.

- [ ] **Step 5: Add configurable retention settings**

Add `AUDIT_RETENTION_DAYS`, `TELEMETRY_RETENTION_DAYS`, and `APPLICATION_LOG_RETENTION_DAYS` to `.env.example`, `compose.yaml`, and `scripts/validate-stack-env.sh`. Parse positive integer values and expose them as policy metadata; do not delete the immutable business audit ledger automatically.

- [ ] **Step 6: Verify**

Run:

```bash
uv run pytest packages/platform-core/tests apps/api/tests/test_api_logging.py apps/api/tests/test_telemetry.py apps/worker/tests/test_logging.py apps/mcp/tests -v
uv run ruff check packages/platform-core apps/api apps/worker apps/mcp
uv run mypy packages/platform-core/src apps/api/src apps/worker/src apps/mcp/src
```

Expected: all commands exit zero and no sensitive fixture value appears in captured output.

- [ ] **Step 7: Commit**

```bash
git add packages/platform-core pyproject.toml apps/api apps/mcp apps/worker .env.example compose.yaml scripts/validate-stack-env.sh uv.lock
git commit -m "feat: enforce shared privacy-safe telemetry"
```

### Task 3: Harden untrusted evidence and model behavior (#49)

**Files:**
- Create: `apps/worker/src/agreement_intelligence_worker/guardrails.py`
- Create: `apps/worker/tests/golden/security/adversarial-documents.json`
- Create: `apps/worker/tests/test_guardrails.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/analysis_provider.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/model_gateway.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/evidence_validation.py`
- Modify: `apps/worker/src/agreement_intelligence_worker/document_understanding.py`
- Modify: `apps/api/src/agreement_intelligence_api/qa/service.py`
- Modify: `apps/mcp/src/agreement_intelligence_mcp/service.py`
- Test: `apps/api/tests/test_grounded_qa.py`
- Test: `apps/mcp/tests/test_read_service.py`

**Interfaces:**
- Produces: `GuardrailDecision(status, reason_codes, policy_version)` and `validate_untrusted_evidence(evidence, allowed_anchor_ids) -> GuardrailDecision`
- Consumes: canonical source blocks, retrieved chunks, provider citation IDs, and requested MCP resources

- [ ] **Step 1: Add adversarial failing cases**

Fixtures must cover direct instruction override, instructions hidden inside clauses, requests to reveal prompts, invented citation IDs, cross-document identifiers, encoded exfiltration requests, and requests for write/tool actions.

- [ ] **Step 2: Run focused tests and confirm failures**

```bash
uv run pytest apps/worker/tests/test_guardrails.py apps/api/tests/test_grounded_qa.py apps/mcp/tests/test_read_service.py -v
```

Expected: new guardrail cases fail because no versioned decision exists.

- [ ] **Step 3: Implement deterministic guardrail decisions**

Use:

```python
@dataclass(frozen=True)
class GuardrailDecision:
    status: Literal["allow", "review", "block"]
    reason_codes: tuple[str, ...]
    policy_version: str = "untrusted-evidence.v1"
```

The validator checks requested citations against the supplied allow-list, rejects tool/write instructions from evidence, and returns `review` for ambiguous injection markers. It never grants access or rewrites authorization scope.

- [ ] **Step 4: Strengthen provider instructions and output validation**

Wrap evidence in a typed data payload, state that document content is untrusted, validate every returned citation against the request allow-list, and convert invalid output to `needs_review`, `insufficient_evidence`, or the existing safe deterministic fallback.

- [ ] **Step 5: Persist safe guardrail provenance**

Record policy version, status, and reason codes with analysis/Q&A artifacts and spans. Do not persist the suspicious source text or raw provider response in telemetry.

- [ ] **Step 6: Verify**

```bash
uv run pytest apps/worker/tests/test_guardrails.py apps/worker/tests/test_analysis_validation.py apps/worker/tests/test_evidence_validation.py apps/api/tests/test_grounded_qa.py apps/mcp/tests/test_read_service.py -v
make check
```

Expected: adversarial cases cannot produce unauthorized evidence, unsupported accepted claims, prompt leakage, or MCP write behavior.

- [ ] **Step 7: Commit**

```bash
git add apps/worker apps/api/src/agreement_intelligence_api/qa apps/api/tests/test_grounded_qa.py apps/mcp
git commit -m "feat: harden untrusted evidence boundaries"
```

### Task 4: Perform the independent pre-publication review

**Files:**
- Create: `docs/reviews/2026-08-22-pre-publication-review.md`
- Read: application, migration, Compose, Terraform, CI, test, and documentation files

**Interfaces:**
- Consumes: merged Tasks 1–3
- Produces: evidence-backed blocker/high/improvement/cloud-deferred findings with issue links

- [ ] **Step 1: Run automated discovery**

Run:

```bash
make check
pnpm audit --prod --audit-level high
uv run pip-audit
make terraform-check
```

Run the repository’s full-history gitleaks scan and the RLS integration test against a disposable PostgreSQL database.

- [ ] **Step 2: Review trust boundaries**

Inspect authentication/logout, permission mapping, tenant queries, RLS policies, object keys, permanent deletion, immutable versions, queue/outbox idempotency, provider fallback, citations, audit writes, package downloads, MCP authorization, and browser error states.

- [ ] **Step 3: Write the review report**

For every finding record: severity (`release blocker`, `high`, `improvement`, `cloud deferred`), affected file/line, reproducible evidence, risk, and issue URL. Record `No finding` for a reviewed boundary that has adequate evidence.

- [ ] **Step 4: Create issues before fixes**

Attach local blocker/high findings beneath #63. Attach cloud-deferred findings beneath the deferred epic. Do not change source code in the review-report PR.

- [ ] **Step 5: Verify the report**

```bash
pnpm exec prettier --check docs/reviews/2026-08-22-pre-publication-review.md
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add docs/reviews/2026-08-22-pre-publication-review.md
git commit -m "docs: record pre-publication security review"
```
