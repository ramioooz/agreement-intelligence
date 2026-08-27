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

## Non-destructive automated gate

`scripts/release-check.sh` requires:

- `RELEASE_TEST_POSTGRES_URL` — explicit disposable PostgreSQL database;
- `STACK_ENV_FILE` — validated ignored stack environment, default `.env`;
- `STACK_PROJECT_NAME` — exact local demo project, default `agreement-intelligence`;
- a running healthy stack for OpenAPI/stack/E2E checks; and
- installed source, Terraform/LocalStack, audit, and secret-scan tools.

```bash
RELEASE_TEST_POSTGRES_URL=<disposable-postgresql-url> \
STACK_ENV_FILE=.env \
STACK_PROJECT_NAME=agreement-intelligence \
make release-check
```

The script validates tools/environment, documentation, formatting/source/tests/build,
production audits, Git history secret scan, Terraform/LocalStack, stack health/OpenAPI,
forced RLS, deterministic AI evaluation, and the Playwright release project. It refuses a
missing disposable database and never invokes `stack-reset`.

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

| Item | Commit/time | Result | Safe evidence |
| --- | --- | --- | --- |
| Clean setup and tool versions | `24bc47f` / `2026-08-27` | Pass | Node `22.23.1`; pnpm `10.28.0`; uv `0.11.29`; locked installs completed |
| No-key `stack-up` / `stack-check` | `24bc47f` / `2026-08-27` | Pass | Both provider-key variables empty; API, web, worker, MCP, PostgreSQL, Redis, Keycloak, LocalStack, and telemetry services healthy |
| Documentation links/contracts/format | `24bc47f` / `2026-08-27` | Pass | 60 source Markdown files (61 after the generated evaluation report); 47 stable `MQA-*` cases; link, structure, and Prettier checks passed |
| `make check` with disposable PostgreSQL | `24bc47f` / `2026-08-27` | Pass | 64 web tests and 506 Python tests passed; lint, types, CI/auth contracts, and all production builds passed |
| Production dependency audits | `24bc47f` / `2026-08-27` | Pass | pnpm and published Python dependencies: 0 known vulnerabilities; four internal packages are not published on PyPI and are listed as unauditable project packages |
| Full-history secret scan | `24bc47f` / `2026-08-27` | Pass | 226 reachable commits / 4.33 MB scanned; 0 leaks; staged release patch scan also found 0 leaks |
| Terraform/LocalStack | `24bc47f` / `2026-08-27` | Pass | Terraform valid; Checkov 29 passed / 0 failed; emulated apply, encrypted/private bucket, queue/DLQ, secret, and destroy assertions passed |
| Deterministic `make ai-eval` | `24bc47f` / `2026-08-27` | Pass | SHA-256 `f1a10a531f0c3c5c2240c6a65d187dad8caf445749a8bc91582a757bc7157831`; all thresholds passed; 0 tokens, USD cost, and provider latency |
| Playwright release project | `24bc47f` / `2026-08-27` | Pass | 5 passed / 0 failed / 0 skipped in one worker, including the public repository-to-comparison journey |
| Provider contract/no-key degradation | `24bc47f` / `2026-08-27` | Pass | API/worker configuration tests passed; deterministic analysis and lexical retrieval remained usable without a key; provider provenance stayed empty rather than fabricated |
| Live provider smoke | `24bc47f` / `2026-08-27` | Blocked | No authorized provider secret was available; no external request was sent and no secret was read or logged |
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
