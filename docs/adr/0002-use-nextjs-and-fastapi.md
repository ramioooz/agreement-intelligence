# ADR 0002: Use Next.js and FastAPI

## Status

Accepted

## Context

The product needs a rich authenticated document-review interface, secure
server-side identity sessions, a typed business API, asynchronous Python
document processing, and strong access to the Python AI and document ecosystem.

A static React single-page application could communicate directly with the
Python API, but it would either expose provider tokens to browser JavaScript or
move all identity-session handling into the API. A single JavaScript runtime
would simplify language count but weaken access to the selected document and
AI tooling. A server-rendered Python UI would reduce language count but provide
a less suitable foundation for the interaction-heavy review workspace.

## Decision

Use Next.js, which is a React framework, for the web application and FastAPI
for the authoritative business API.

### Web responsibilities

Next.js owns:

- React UI, routing, layouts, and accessibility;
- the branded sign-in entry point;
- OIDC callbacks and secure server-side session handling;
- route protection;
- presentation-specific data composition; and
- the future public product and documentation pages.

It does not implement agreement rules, resource authorization, workflow state,
or provider integration.

### API responsibilities

FastAPI owns:

- business commands and queries;
- tenant and resource authorization;
- transaction, idempotency, and optimistic-locking boundaries;
- agreement, playbook, review, search, and administration rules;
- audit and outbox events; and
- external integration interfaces used by business operations.

The API publishes an OpenAPI specification. The web application uses a
generated TypeScript client rather than duplicating request and response types.

### Worker responsibilities

Python workers reuse the same domain and integration packages as the API for
document parsing, OCR, model operations, retrieval, comparison, exports, and
workflow continuation.

### Communication

The browser communicates with the web application over HTTPS. The web
application sends authenticated API calls to FastAPI. Long-running work is
requested through the API and executed asynchronously by workers.

Business logic must not be duplicated in Next.js server actions or route
handlers.

## Alternatives considered

### Vite with React

This offers an excellent static SPA development experience and a simple S3
deployment. It is rejected for the initial architecture because server-side
OIDC session handling and the backend-for-frontend boundary are valuable for
this security-sensitive application.

### Full-stack Next.js

Using one framework for UI and business APIs reduces runtime count. It is
rejected because Python is the primary language for document processing, AI
evaluation, and orchestration, and the business API should remain independent
of the presentation framework.

### Python-rendered web application

This reduces languages but is less appropriate for a highly interactive,
side-by-side legal review workspace.

### Separate static React application with FastAPI-owned sessions

This is viable and may reduce web runtime responsibilities. It is not selected
because the server-side web boundary provides a clean place for identity
callbacks, secure sessions, and future public pages.

## Consequences

### Positive

- The UI retains the React ecosystem and gains framework routing and
  server-side session handling.
- Business logic stays in a typed, independently testable Python API.
- Python API and worker packages can share domain concepts.
- OpenAPI provides a contract between the two runtimes.
- Identity tokens remain outside browser JavaScript.

### Negative

- The team maintains TypeScript and Python toolchains.
- Requests may cross a web boundary before reaching the API.
- Care is required to avoid duplicating API logic in the web application.
- Cross-runtime tracing and local startup require deliberate tooling.

### Required controls

- Generate the TypeScript API client from OpenAPI in CI.
- Test API compatibility and authentication flows end to end.
- Keep server actions presentation-oriented.
- Propagate correlation identifiers across web, API, and worker boundaries.
- Record a replacement framework decision in a new ADR.
