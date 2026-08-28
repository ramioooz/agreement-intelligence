# Security policy

## Supported versions

Agreement Intelligence is currently pre-1.0. Security fixes are supported on the
latest commit of `main`; there are no maintained release branches yet. After tagged
releases begin, this table will be updated with supported version lines.

| Version | Supported |
| --- | --- |
| Latest `main` | Yes |
| Older commits and forks | No |

This policy does not claim that the local stack has been validated for internet-facing
production use or in a live AWS account. See the [threat model](docs/security/threat-model.md)
and [roadmap](docs/roadmap.md) for those boundaries.

## Report a vulnerability privately

Do **not** open a public issue, pull request, discussion, or paste containing an
unpatched vulnerability, exploit, credential, token, private agreement, personal data,
or tenant identifier.

Use GitHub's private vulnerability reporting flow:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Submit the report without real customer data or working production credentials.

If private reporting is unavailable, contact the repository owner through the GitHub
profile linked from the repository and ask for a private reporting channel. Do not send
sensitive details until that channel is confirmed.

## What to include

Provide enough non-sensitive evidence to reproduce and assess the issue:

- affected commit, component, route, and configuration;
- impact and the security boundary crossed;
- minimal steps using synthetic data and local test credentials;
- expected and observed results;
- relevant safe logs, status codes, trace IDs, or screenshots;
- whether tenant isolation, authentication, authorization, document parsing, AI
  grounding, secret handling, deletion, or package integrity is involved; and
- a proposed mitigation, if known.

Remove tokens, cookies, provider responses, prompts, document text, emails, filesystem
paths, and environment values from evidence. A report does not need a live exploit to
be useful.

## Response goals

These are targets, not service-level guarantees:

- acknowledge a complete report within 3 business days;
- provide an initial severity and scope assessment within 10 business days;
- keep the reporter informed when material status changes; and
- coordinate disclosure after a fix and verification evidence are available.

Time-sensitive containment may precede a complete root-cause analysis. The owner decides
release timing, credit, CVE requests, and disclosure based on risk and available evidence.

## Scope

Reports are especially welcome for:

- authentication, logout, session, and OIDC validation failures;
- cross-organization or cross-workspace access;
- row-level-security bypasses;
- unsafe PDF or DOCX handling and denial-of-service paths;
- object-key, deletion, audit, or final-package integrity failures;
- prompt injection, ungrounded citations, or retrieval leakage;
- MCP authentication, authorization, or write-capability regressions;
- secrets in source, logs, telemetry, screenshots, build artifacts, or history; and
- vulnerable production dependencies or unsafe container/infrastructure defaults.

The following are normally out of scope unless they demonstrate a new boundary failure:

- attacks requiring physical access to the developer machine;
- denial of service caused only by intentionally undersizing a local demo;
- model quality disagreements without a reproducible grounding, safety, or evaluation
  failure;
- social engineering of maintainers;
- automated scanner output without a verified affected path; and
- live AWS behavior, because no production AWS environment is supplied by this project.

## Safe research rules

- Use a local clone, synthetic agreements, and accounts you control.
- Do not access, modify, retain, or disclose another person's data.
- Do not test against infrastructure you do not own or have permission to assess.
- Do not degrade shared services, persist access, or exfiltrate data.
- Stop when you have demonstrated the minimum evidence needed.
- Never commit or transmit a real provider key.

Good-faith research that follows these rules will be assessed on its technical evidence
and handled through the private process above.

## Secret exposure

Treat any committed or shared secret as compromised. Revoke or rotate it at its source,
remove it from active configuration, preserve non-sensitive incident evidence, and use
the [compromised credential runbook](docs/operations/runbooks/compromised-credential.md).
Deleting a file or commit is not a substitute for rotation.

[Back to top](#security-policy)
