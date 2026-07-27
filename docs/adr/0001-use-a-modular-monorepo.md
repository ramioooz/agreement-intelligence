# ADR 0001: Use a Modular Monorepo

## Status

Accepted

## Context

The product includes a TypeScript web application, Python API and worker
processes, shared domain packages, evaluation datasets, infrastructure, and
documentation. End-to-end features regularly change several of these parts
together.

The project is initially built and operated by a small team. Splitting each
runtime or package into a separate repository would introduce release
coordination, cross-repository pull requests, version publication, duplicated
automation, and local setup overhead before independent ownership or scaling
requires it.

A single unstructured application would avoid repository coordination but
would make domain boundaries unclear and make later extraction expensive.

## Decision

Use one modular monorepo with three separately deployable applications:

```text
apps/web
apps/api
apps/worker
```

Reusable logic is organized into focused packages:

```text
packages/ai-core
packages/agreement-analysis
packages/document-processing
packages/retrieval
packages/shared
```

Evaluation, infrastructure, documentation, sample data, scripts, and
cross-application tests remain first-class top-level areas.

The repository uses:

- `pnpm` workspaces for TypeScript dependencies;
- `uv` workspaces for Python dependencies;
- a small root command surface for bootstrap, development, verification, and
  cleanup; and
- Docker Compose for local dependencies.

Applications may depend on packages. Domain packages must not depend on
application routing, UI, or deployment entry points. Internal package
interfaces remain explicit and testable.

The system begins as a modular monolith with separate web, API, worker, and
dispatcher processes. A module becomes an independent service only when
measured scaling, security isolation, failure isolation, or team ownership
requires it.

## Alternatives considered

### Multiple repositories

This provides strong ownership and independent release histories, but creates
avoidable coordination and local-development cost for the first release.

### Microservices from the start

This enables independent deployment but adds distributed transactions,
service discovery, contract versioning, network failure, and observability
complexity without a demonstrated need.

### One application with no internal modules

This is initially fast but couples document processing, legal rules,
retrieval, HTTP handling, and deployment. It is rejected because those
responsibilities change for different reasons.

### Advanced monorepo build systems

Large-scale build graph tooling may eventually improve caching and selective
execution. It is deferred until repository scale makes the simpler workspace
and root-command approach insufficient.

## Consequences

### Positive

- One pull request can deliver an end-to-end feature atomically.
- Local development and CI use one versioned source tree.
- Shared schemas and generated clients remain synchronized.
- Architecture, infrastructure, evaluation, and code evolve together.
- Module boundaries permit later service extraction.

### Negative

- CI must avoid running every expensive check for every small change.
- Python and TypeScript tooling must coexist clearly.
- Poor import discipline could turn the monorepo into a coupled monolith.
- Deployment versions for the applications originate from the same repository.

### Required controls

- Enforce package direction with tests or static checks.
- Keep application entry points thin.
- Give every package one documented responsibility and public interface.
- Use path-aware CI when build time justifies it.
- Record any service extraction in a new ADR.
