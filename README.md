# Agreement Intelligence

Agreement Intelligence is a production-oriented legal document intelligence
platform for financial agreements. It turns uploaded agreements into
structured, cited, reviewable information and supports human-controlled legal
review and approval.

The first product release focuses on Client Agreements and Liquidity Provider
Agreements. Later releases can extend the same architecture to Prime Broker
Agreements, IB Agreements, ISDA documentation, and regulatory documents.

## Planned capabilities

- Secure, tenant-isolated agreement repository
- PDF and DOCX parsing with OCR fallback
- Agreement classification and clause extraction
- Evidence-backed summaries and risk findings
- Versioned legal playbooks and preferred clause positions
- Hybrid search and natural-language questions with citations
- Agreement-version comparison
- Human review, approval, and immutable audit history
- Measured AI quality, security controls, and operational telemetry

## Architecture

Start with the [architecture overview](docs/architecture/overview.md). The
initial decisions are recorded separately:

1. [Use a modular monorepo](docs/adr/0001-use-a-modular-monorepo.md)
2. [Use Next.js and FastAPI](docs/adr/0002-use-nextjs-and-fastapi.md)
3. [Use OIDC authentication](docs/adr/0003-use-oidc-authentication.md)
4. [Use hybrid authorization](docs/adr/0004-use-hybrid-authorization.md)
5. [Use durable asynchronous processing](docs/adr/0005-use-durable-asynchronous-processing.md)

## Delivery

Development proceeds in business-visible increments. Every change is made on a
dedicated branch, linked to an issue, and delivered through a pull request.
Only the repository owner merges changes into `main`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete delivery and review
policy.
