# Public-release evidence

This file defines the evidence contract and records repository-safe results. It never
contains provider keys, tokens, cookies, prompts, provider bodies, or raw agreements.

## Release state

| Gate | Repository evidence | Owner action |
| --- | --- | --- |
| Source quality | Run `make check` with an explicit disposable PostgreSQL URL | Review fresh output on the PR commit |
| Documentation | Link checker, structural contract, Prettier, Markdown lint where available | Confirm first-time usability |
| Dependencies/secrets | Production audits and full-history scan summary only | Privately handle any finding |
| Infrastructure | Terraform/Checkov/LocalStack gates | Do not infer live-AWS readiness |
| Stack | Fresh-clone `stack-up`/`stack-check` in no-key mode | Inspect service/status evidence |
| Deterministic AI | `make ai-eval` report/checksum | Review threshold summary |
| Browser/API | Playwright release project plus `MQA-*` owner pass | Record Pass/Fail/Blocked per case |
| Provider contract | No key exposure; smoke only when an ignored key is already safely available | Owner authorizes external request |
| Visibility | Not automated | Owner decides after manual pass |

The branch/PR evidence below records the final automated rehearsal. The owner manual pass
remains Pending until every release-critical case is executed.

PR #247 depends on #246 for the documented read-only final-package GET route. Until #246 is
merged and this branch is rebased onto updated `main`, the branch must not be described as
self-contained for that endpoint. The final affected/full gates run again after that rebase.

## Non-destructive automated gate

`scripts/release-check.sh` requires:

- `RELEASE_TEST_POSTGRES_URL` — explicit disposable PostgreSQL database;
- `STACK_ENV_FILE` — validated ignored stack environment, default `.env`;
- `STACK_PROJECT_NAME` — exact local demo project, default `agreement-intelligence`;
- a running healthy stack for OpenAPI/stack/E2E checks; and
- installed source, Terraform/LocalStack, audit, and secret-scan tools.

Create ignored `.env.release-test.local` in an editor, make it owner-readable only, and
store the disposable URL there so the credential never enters a command argument, process
list, or shell history:

```dotenv
RELEASE_TEST_POSTGRES_URL=postgresql://USER:PASSWORD@127.0.0.1:PORT/agreement_intelligence_public_release
```

```bash
chmod 600 .env.release-test.local
set -a
. ./.env.release-test.local
set +a
STACK_ENV_FILE=.env STACK_PROJECT_NAME=agreement-intelligence make release-check
unset RELEASE_TEST_POSTGRES_URL
```

The script validates tools/environment, documentation, formatting/source/tests/build,
production audits, Git history secret scan, Terraform/LocalStack, stack health/OpenAPI,
forced RLS, deterministic AI evaluation, and the Playwright release project. It refuses a
missing disposable database and never invokes `stack-reset`.

The accepted Python audit boundary is exact: zero unignored/actionable findings, with two
development-tool exceptions that have no published fixed version. Ragas `0.3.9`
(`PYSEC-2026-3046`) is used only by the owner-triggered assisted evaluator, which does not
invoke the affected multimodal URL/file retrieval. Its DiskCache `5.6.3` dependency
(`PYSEC-2026-2447`) is an owner-local ephemeral cache that is not writable by untrusted
users. The gate names only those IDs and fails on every other advisory; see
[Unified quality](../evaluation/unified-quality.md#dependency-boundary).

## Fresh-clone rehearsal

Use a disposable temporary directory and follow only the root README/getting-started guide:

1. clone the exact branch/commit;
2. generate a local `.env` with no remaining placeholders and empty provider keys;
3. run `make setup`, `make stack-up`, and `make stack-check`;
4. generate synthetic fixtures and execute no-key repository/deterministic/lexical checks;
5. run documentation, source, RLS, Terraform/LocalStack, deterministic evaluation, and
   release browser checks;
6. record versions, UTC times, exit codes, safe counts, and artifact checksums; and
7. run `make stack-down` and remove only the disposable clone after preserving safe evidence.

Do not copy a real key into the clone. If the owner already has a safely stored ignored key,
provider verification is a separate opt-in: add it without logging, recreate API/worker,
run `make provider-smoke`, process one synthetic agreement, verify safe provenance/
embeddings/semantic retrieval/cited answer, remove the key and clone, and record only safe
metadata. When no key is safely available, record the provider live call as Blocked while
passing the configured-provider contract and no-key behavior.

## Evidence record

Automated rehearsal of commit `24bc47fd17e850160aadcffabd4b9297105c1aab` completed
at `2026-08-27T10:17:02Z` in a disposable fresh clone. The follow-up evidence-only commit
does not alter the exercised source, configuration, or test paths.

Hosted Linux verification then exposed FPDF wall-clock metadata in the final-package retry
path. Focused regressions failed before the correction and passed after commit `764b550` made
the PDF creation date stable from persisted workflow data. The complete release gate and the
exact approval browser journey passed again at `2026-08-27T10:35:02Z`.

The review-correction candidate was exercised again at `2026-08-27T15:46:27Z`. Focused
regressions covered tenant-scope restoration after rollback/commit, no-key configuration,
synthetic fixtures, comparison rendering, and the condition-based approval journey. The
complete deterministic release gate then passed against the isolated
`agreement-intelligence-public-release` stack.

| Item | Commit/time | Result | Safe evidence |
| --- | --- | --- | --- |
| Clean setup and tool versions | `24bc47f` / `2026-08-27` | Pass | Node `22.23.1`; pnpm `10.28.0`; uv `0.11.29`; locked installs completed |
| No-key `stack-up` / `stack-check` | `24bc47f` / `2026-08-27` | Pass | Both provider-key variables empty; API, web, worker, MCP, PostgreSQL, Redis, Keycloak, LocalStack, and telemetry services healthy |
| Documentation links/contracts/format | correction candidate / `2026-08-27` | Pass | 60 tracked source Markdown files; 47 stable `MQA-*` cases; link, structure, fixture, no-key, and Prettier checks passed |
| `make check` with disposable PostgreSQL | correction candidate / `2026-08-27` | Pass | 64 web tests and 512 Python tests passed; lint, types across 192 Python files, CI/auth contracts, and all production builds passed |
| Production dependency audits | correction candidate / `2026-08-27` | Pass | 0 unignored/actionable findings; accepted dev-tool advisories: Ragas `0.3.9` / `PYSEC-2026-3046` and DiskCache `5.6.3` / `PYSEC-2026-2447`; four internal packages are not published on PyPI and are listed as unauditable project packages |
| Full-history secret scan | correction candidate / `2026-08-27` | Pass | 255 reachable commits / 4.56 MB scanned; 0 leaks; the materialized staged patch scan covered 1.03 MB and found 0 leaks |
| Terraform/LocalStack | correction candidate / `2026-08-27` | Pass | Terraform valid; Checkov 29 passed / 0 failed; emulated apply, encrypted/private bucket, queue/DLQ, secret, and destroy assertions passed |
| Deterministic `make ai-eval` | correction candidate / `2026-08-27` | Pass | SHA-256 `f1a10a531f0c3c5c2240c6a65d187dad8caf445749a8bc91582a757bc7157831`; all thresholds passed; 0 tokens, USD cost, and provider latency |
| Playwright release project | correction candidate / `2026-08-27` | Pass | 5 passed / 0 failed / 0 skipped in one worker in 31.2 seconds, including approval and repository-to-comparison journeys |
| Synthetic release media | correction candidate / `2026-08-27` | Pass | `grounded-search.png`: 227,649 bytes, SHA-256 `33051e8b60d44f1e817b3dbba8c3805af464311124b9c493c51e8cefbcf8bdff`; `public-release-demo.webm`: 656,070 bytes, 8.84 seconds, SHA-256 `1b2fa90767015824a8ef855d37fc77fc9f1e1801e77b23721e2a9177d136207e` |
| Provider contract/no-key degradation | correction candidate / `2026-08-27` | Pass | API/worker configuration tests passed; recreated containers were inspected and rejected hosted/openai-compatible settings; deterministic analysis and lexical retrieval remained usable without a key; provider provenance stayed empty rather than fabricated |
| Live provider smoke | correction candidate / `2026-08-27` | Blocked | No authorized provider secret was available; only the opt-in configuration contract was verified, no external request was sent, and no secret was read or logged |
| Owner manual `MQA-*` pass | PR head / pre-visibility | Pending | 47 cases remain for owner execution and evidence review before the visibility decision |

## Honest release limitations

- Manual QA and the owner visibility decision cannot be automated.
- External provider quality/latency/cost is variable; a live call is not a deterministic
  release gate.
- No OCR engine exists; `ocr_required` is diagnostic only.
- Historical provider enrichment is not automatically backfilled.
- LocalStack and Docker evidence does not validate live AWS.

See [Manual QA](manual-test-plan.md), [API testing](api-testing.md), and
[Evidence template](evidence-template.md).

[Back to top](#public-release-evidence)
