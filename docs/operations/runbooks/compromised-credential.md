# Compromised credential

## Trigger and impact

A credential appears in logs, source, screenshots, shell history, or an untrusted system;
unexpected authentication/provider activity is observed; or a secret owner reports loss.

## Safe diagnostics

Do not echo, validate, or paste the suspected value. Identify only its type, owner,
configured consumers, exposure window, and safe audit/correlation IDs. Inspect local
files with filenames and key names only.

## Containment and recovery

1. Revoke or rotate the credential at its authoritative provider immediately.
2. Replace the value in the untracked `.env`; never commit it.
3. For OIDC client/admin credentials, restart Keycloak bootstrap and dependent services.
   For provider or AWS-compatible credentials, restart API, worker, MCP, and bootstrap
   services as applicable.
4. Run `make stack-check` and the smallest relevant smoke path.
5. Remove exposed copies from logs or external systems according to their retention
   controls; do not rewrite Git history without repository-owner approval.

## Verification and evidence

Verify the old credential is rejected, the replacement succeeds, and no secret value is
present in application logs or audit metadata. Record secret type, rotation timestamp,
systems checked, safe event IDs, and owner—not the credential itself.

## Escalation and residual risk

Escalate immediately if a real tenant, cloud account, signing key, or production provider
credential is involved. Local rotation does not revoke copies outside the workstation.
