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
| Browser/API | Playwright release project plus the 14-test manual/API pass | Review the dated observed result per test |
| Provider contract | No key exposure; smoke only when an ignored key is already safely available | Owner authorizes external request |
| Visibility | Not automated | Owner decides after manual pass |

The historical branch/PR evidence below records the original automated rehearsal. The
current 14-test manual/API result is maintained in the combined
[Manual QA and API guide](manual-test-plan.md).

PR #246 merged into `main` at `e728cf2`. PR #247 was then rebased onto that revision and
rehearsed from a disposable clean clone, so the branch now includes the documented durable
worker generation and read-only final-package GET behavior.

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

Review correction commit `6ab8720` was exercised again at `2026-08-27T15:46:27Z`. Focused
regressions covered tenant-scope restoration after rollback/commit, no-key configuration,
synthetic fixtures, comparison rendering, and the condition-based approval journey. The
complete deterministic release gate then passed against the isolated
`agreement-intelligence-public-release` stack.

Final review-correction commit `e224598` was exercised at `2026-08-27T16:50:31Z` against
that isolated no-key stack. Focused checks covered pre-commit jurisdiction normalization,
the executable second-tenant agreement/citation/review/package fixture, actual document
duplicate semantics, and the imported Insomnia multipart/idempotency contract. The exact
release gate rebuilt and inspected API/worker containers, ran every source, audit,
infrastructure, deterministic-evaluation, and browser gate, and passed.

After #246 merged at `e728cf2`, all nine #247 commits were replayed and inspected with
`git range-diff`. The durable worker/read-only GET implementation replaced the superseded
synchronous package-generation conflict hunks, while the #247 tenant-scope reservation
fence remained covered. Rebased source commit `14424442` completed the documented clean-clone
setup, focused conflict-path checks, and exact no-key `make release-check` at
`2026-08-28T06:12:45Z`. The follow-up evidence-only commit does not alter any exercised
source, configuration, or test path.

| Item | Commit/time | Result | Safe evidence |
| --- | --- | --- | --- |
| Clean setup and tool versions | `14424442` / `2026-08-28` | Pass | Node `22.23.1`; pnpm `10.28.0`; uv `0.11.29`; locked installs completed in a disposable clone |
| No-key `stack-up` / `stack-check` | `14424442` / `2026-08-28` | Pass | Both provider-key variables empty; API/worker were rebuilt, recreated, and inspected; API, web, worker, MCP, PostgreSQL, Redis, Keycloak, LocalStack, and telemetry services were healthy |
| Documentation links/contracts/format | `14424442` / `2026-08-28` | Pass | Historical pre-consolidation link, structure, fixture, no-key, YAML, OpenAPI-path, Prettier, and Ruff checks passed |
| `make check` with disposable PostgreSQL | `14424442` / `2026-08-28` | Pass | 64 web tests and 529 Python tests passed; lint, types across 197 Python files, CI/auth contracts, and all production builds passed |
| Production dependency audits | `14424442` / `2026-08-28` | Pass | 0 unignored/actionable findings; accepted dev-tool advisories: Ragas `0.3.9` / `PYSEC-2026-3046` and DiskCache `5.6.3` / `PYSEC-2026-2447`; four internal packages are not published on PyPI and are listed as unauditable project packages |
| Full-history secret scan | `14424442` / `2026-08-28` | Pass | 244 reachable commits / 4.61 MB scanned with redaction; 0 leaks |
| Terraform/LocalStack | `14424442` / `2026-08-28` | Pass | Terraform valid; Checkov 29 passed / 0 failed; emulated apply, encrypted/private bucket, queue/DLQ, secret, and destroy assertions passed |
| Deterministic `make ai-eval` | `14424442` / `2026-08-28` | Pass | SHA-256 `f1a10a531f0c3c5c2240c6a65d187dad8caf445749a8bc91582a757bc7157831`; all thresholds passed; 0 tokens, USD cost, and provider latency |
| Playwright release project | `14424442` / `2026-08-28` | Pass | 5 passed / 0 failed / 0 skipped in one worker in 27.5 seconds, including approval and repository-to-comparison journeys |
| Synthetic release media | `14424442` / `2026-08-28` | Pass | `grounded-search.png`: 227,649 bytes, SHA-256 `33051e8b60d44f1e817b3dbba8c3805af464311124b9c493c51e8cefbcf8bdff`; `public-release-demo.webm`: 656,070 bytes, 8.84 seconds, SHA-256 `1b2fa90767015824a8ef855d37fc77fc9f1e1801e77b23721e2a9177d136207e` |
| Provider contract/no-key degradation | `14424442` / `2026-08-28` | Pass | API/worker configuration tests passed; recreated containers were inspected and rejected hosted/openai-compatible settings; deterministic analysis and lexical retrieval remained usable without a key; provider provenance stayed empty rather than fabricated |
| Live provider smoke | `14424442` / `2026-08-28` | Blocked | No authorized provider secret was available; only the opt-in configuration contract was verified, no external request was sent, and no secret was read or logged |
| Consolidated manual/API pass | `docs/public-manual-qa` / `2026-08-28` | Partial | 14 critical tests evaluated: 9 Pass, 1 Pass with note, 4 Partial; exact observations and unexecuted portions are in the combined guide |

## Honest release limitations

- The owner visibility decision remains manual; the 14-test result contains two explicitly
  Partial observations and must not be represented as an all-pass certification.
- External provider quality/latency/cost is variable; a live call is not a deterministic
  release gate.
- No OCR engine exists; `ocr_required` is diagnostic only.
- Historical provider enrichment is not automatically backfilled.
- LocalStack and Docker evidence does not validate live AWS.

See the combined [Manual QA and API guide](manual-test-plan.md) and
[Evidence template](evidence-template.md).

[Back to top](#public-release-evidence)
