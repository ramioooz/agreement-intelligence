# Contributing

This repository uses issue-driven, pull-request-only delivery. The repository
owner is solely responsible for merging changes into `main`.

## 1. Choose an issue

Before starting:

1. confirm the issue has an outcome and testable acceptance criteria;
2. identify dependencies and unresolved decisions;
3. set its execution mode;
4. move it to `In progress`; and
5. keep concurrent work small.

If the implementation changes architecture, security boundaries, or accepted
scope, update the issue before expanding the change.

## 2. Create a dedicated branch

Start from the current remote `main`:

```bash
git switch main
git pull --ff-only
git switch -c <type>/<short-description>
```

Allowed branch prefixes:

```text
feat/
fix/
docs/
test/
refactor/
chore/
infra/
```

Examples:

```text
docs/architecture-baseline
feat/agreement-upload
fix/duplicate-processing-job
```

Do not commit or push implementation changes directly to `main`.

## 3. Keep delivery metadata vendor-neutral

Do not place assistant, vendor, model-provider, or tool branding in:

- branch names;
- commit authorship or messages;
- pull-request titles or descriptions;
- changelogs or release notes; or
- generated attribution.

Describe the product change itself. Necessary technical identifiers may appear
in source code or technical documentation when they are part of the runtime
design, configuration, or dependency contract.

## 4. Commit intentionally

Use Conventional Commits:

```text
<type>(optional-scope): <imperative summary>
```

Examples:

```text
docs: define architecture and delivery conventions
feat(api): create agreement upload instruction
fix(worker): prevent duplicate processing jobs
test(auth): cover cross-tenant agreement access
```

Commit rules:

- stage only files that belong to the issue;
- keep commits reviewable and logically complete;
- never commit credentials, access tokens, private agreements, or production
  data;
- do not bypass verification hooks;
- do not rewrite shared branch history without owner approval; and
- do not add generated attribution.

## 5. Open a pull request

Every pull request must:

- target `main`;
- link its issue with `Closes #<number>` when appropriate;
- explain what changed and why;
- describe user, developer, security, or operational impact;
- list verification commands and results;
- identify migrations, compatibility concerns, and residual risks;
- include screenshots or a recording for user-visible changes; and
- include evaluation deltas for AI-facing changes.

Use a draft pull request while work or verification is incomplete. Move the
linked issue to `In review` when the change is ready for owner review.

## 6. Verification expectations

Run the narrow checks during development and the complete relevant checks
before requesting review.

Pull requests targeting `main` run the source-quality CI gate automatically.
The current gate installs locked dependencies, runs `make check`, and checks
for whitespace errors with `git diff --check`. Docker stack checks, dependency
audits, secret scanning, and container scanning are intentionally handled by
later security-hardening work.

| Change | Minimum evidence |
| --- | --- |
| Documentation | Markdown structure, internal links, diagrams, and consistency review |
| Web | Lint, type-check, unit/component tests, accessibility check, build, and visual evidence |
| API | Lint, type-check, unit/integration tests, contract tests, and authorization cases |
| Worker | Unit/integration tests, duplicate delivery, retries, timeouts, and failure recovery |
| Database | Forward migration, constraints, rollback or recovery plan, and tenant-isolation tests |
| AI behaviour | Frozen evaluation results, baseline deltas, latency, cost, and changed-case review |
| Security | Abuse cases, least-privilege review, secret scan, and relevant threat-model update |
| Infrastructure | Format, validate, plan, policy/security checks, and cost-impact notes |

If a relevant check cannot run, state why and what evidence replaces it. Do not
present an unexecuted check as passing.

## 7. Review and merge

The repository owner:

1. reviews the diff and verification evidence;
2. requests changes or approves the pull request;
3. decides when to merge; and
4. updates the issue and project state after merge.

Automated assistants and collaborators must not:

- push directly to `main`;
- approve on behalf of the owner;
- merge pull requests;
- dismiss review findings without owner direction; or
- change repository visibility.

## 8. Definition of done

A change is done only when:

- all issue acceptance criteria are satisfied;
- relevant automated and manual checks pass;
- security and tenant-isolation effects are addressed;
- user-visible behaviour is demonstrated;
- AI-facing changes include measured evaluation evidence;
- documentation and operational notes are current;
- the owner has reviewed and merged the pull request; and
- the project item is moved to `Done`.

## 9. Data and security

Use only synthetic, generated, public-domain, or otherwise legally reusable
agreements in the repository and its tests.

Immediately stop and notify the owner if a change exposes:

- credentials or secrets;
- private or regulated agreement data;
- cross-tenant access;
- unsafe external actions;
- unverifiable legal claims; or
- a destructive migration without a tested recovery path.
