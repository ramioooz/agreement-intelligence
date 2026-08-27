# Documentation index

Use this page to choose the shortest trustworthy path for your role. The root
[README](../README.md) is the product overview and first entry point.

## Start here

| Audience | Document | Purpose |
| --- | --- | --- |
| First-time operator | [Getting started](getting-started.md) | Exact prerequisites, safe configuration, startup, identities, no-key/provider modes, shutdown, and first checks |
| Product evaluator or QA owner | [Manual QA plan](testing/manual-test-plan.md) | Stable `MQA-*` cases, evidence, cleanup, negative/security/accessibility/recovery coverage, traceability |
| API evaluator | [API and Insomnia testing](testing/api-testing.md) | Safe token handling, query scope, request contracts, negative cases, collection import |
| Architect or security reviewer | [Architecture overview](architecture/overview.md) | Local components, data flows, authorization, retrieval, approval, MCP, telemetry, AWS boundary |
| Operator | [Platform operations](operations/platform-foundation.md) | Services, health, provider modes, runbooks, backups, Terraform/LocalStack and recovery |
| Contributor | [Contributing](../CONTRIBUTING.md) | Issue/branch/worktree/PR policy, checks, data and documentation rules |

## Product, architecture, and decisions

| Document | Audience and purpose |
| --- | --- |
| [Architecture overview](architecture/overview.md) | As-built local architecture, diagrams, sources of truth, security and deployment boundaries |
| [ADR 0001: modular monorepo](adr/0001-use-a-modular-monorepo.md) | Why applications share one repository with explicit package boundaries |
| [ADR 0002: Next.js and FastAPI](adr/0002-use-nextjs-and-fastapi.md) | Web/API framework decision |
| [ADR 0003: OIDC](adr/0003-use-oidc-authentication.md) | Authentication boundary |
| [ADR 0004: hybrid authorization](adr/0004-use-hybrid-authorization.md) | Application permissions plus tenant database controls |
| [ADR 0005: durable asynchronous processing](adr/0005-use-durable-asynchronous-processing.md) | Outbox, queue, worker, retries, and idempotency |
| [Secure document uploads](secure-document-upload.md) | File validation, parser isolation/resource bounds, and `ocr_required` |

Historical design and implementation plans remain under `docs/plans/` and
`docs/superpowers/` for provenance. They may describe planned steps; current behavior is
owned by the root README, current architecture, source, API schema, and operations guides.

## Security, privacy, and responsible AI

| Document | Audience and purpose |
| --- | --- |
| [Security policy](../SECURITY.md) | Private vulnerability reporting, scope, response goals, secret handling |
| [Threat model](security/threat-model.md) | Assets, actors, trust boundaries, threats, controls, invariants, residual risk |
| [Responsible AI](security/responsible-ai.md) | Human decision boundary, evidence controls, provider/privacy duties, limitations |
| [Immutable build inputs](security/immutable-build-inputs.md) | Pinned action/image provenance and update workflow |
| [Pre-publication review](reviews/2026-08-22-pre-publication-review.md) | Revision-scoped findings and historical release recommendation; read with current fixes and evidence |

## Testing and release evidence

| Document | Audience and purpose |
| --- | --- |
| [Manual QA plan](testing/manual-test-plan.md) | End-to-end browser/API/MCP/operations execution with stable IDs |
| [Synthetic test data](testing/test-data.md) | Approved identities, fixtures, naming, and prohibited data |
| [Evidence template](testing/evidence-template.md) | Pass/Fail/Blocked record without secrets or agreement content |
| [Release evidence](testing/release-evidence.md) | Clean-clone, no-key/provider contract, automated gate, owner sign-off status |
| [API testing](testing/api-testing.md) | Insomnia setup, requests, expected success/denial, cleanup |
| [Insomnia collection](testing/insomnia/agreement-intelligence.yaml) | Importable placeholder-only request collection |

## Evaluation and quality

| Document | Audience and purpose |
| --- | --- |
| [Unified AI quality](evaluation/unified-quality.md) | Deterministic release gate and opt-in assisted report |
| [Retrieval quality](evaluation/retrieval-quality.md) | Retrieval, grounded-answer, citation, latency, and cost metrics |
| [Version-comparison baseline](evaluation/version-comparison-baseline.md) | Alignment/materiality evaluation boundary |
| [Local performance baseline](evaluation/local-performance-baseline.md) | Synthetic local capacity/recovery evidence and cloud limitations |
| `tests/performance/README.md` | Opt-in k6 local load instructions |
| `tests/resilience/README.md` | Duplicate, timeout, restart, queue, and database recovery instructions |

## Operations

| Document | Audience and purpose |
| --- | --- |
| [Platform operations](operations/platform-foundation.md) | Local service map, modes, health, observability, recovery, cloud boundary |
| [Backup and restore](operations/backup-restore.md) | PostgreSQL/LocalStack S3 backup, checksum, restore, local RPO/RTO |
| [Observability](operations/observability.md) | Optional Langfuse/OTLP profile and safe attribute boundary |
| [Local service objectives](operations/service-objectives.md) | Regression objectives, not cloud SLAs |
| [Incident runbooks](operations/runbooks/index.md) | Provider outage, stuck work, queue backlog, bad model, credential, tenant access |
| [Terraform/LocalStack](../infra/terraform/README.md) | Local verification and owner-authorized AWS migration boundary |

## Limitations and roadmap

[Roadmap and room for improvement](roadmap.md) distinguishes locally implemented behavior
from provider adapters, OCR, automatic backfill, live AWS validation, federation, managed
recovery, broader evaluation, and UX/accessibility improvements.

[Back to top](#documentation-index)
