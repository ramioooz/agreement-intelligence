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

The branch/PR evidence section is updated after the final rehearsal. The owner manual pass
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

Populate on the PR commit:

| Item | Commit/time | Result | Safe evidence |
| --- | --- | --- | --- |
| Clean setup and tool versions | Pending | Pending | Version list |
| No-key `stack-up` / `stack-check` | Pending | Pending | Exit/status summary |
| Documentation links/contracts/format | Pending | Pending | File/link/case counts |
| `make check` with disposable PostgreSQL | Pending | Pending | Test/build counts |
| Production dependency audits | Pending | Pending | Exit/finding counts |
| Full-history secret scan | Pending | Pending | Commit/file scan counts only |
| Terraform/LocalStack | Pending | Pending | Exit/resource assertions |
| Deterministic `make ai-eval` | Pending | Pending | Report checksum/threshold summary |
| Playwright release project | Pending | Pending | Passed/failed/skipped counts |
| Provider contract/no-key degradation | Pending | Pending | Mode and safe state summary |
| Live provider smoke | Pending | Pending/Blocked | Safe model/latency/usage/validation only |
| Owner manual `MQA-*` pass | Pending | Pending | Case-result matrix |

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
