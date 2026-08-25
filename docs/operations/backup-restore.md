# Local backup and restore

This procedure protects the local PostgreSQL application database and the configured
LocalStack S3 document bucket. It is a development and demonstration recovery path,
not evidence that an AWS disaster-recovery design works.

## Recovery objectives

The accepted local operating assumption is one backup every 24 hours, so the local
recovery-point objective (RPO) is **24 hours**. Run a backup before any destructive
maintenance to reduce the possible loss window.

Repeated isolated full-stack rehearsals on 2026-08-25 completed backups in **1–2
seconds** and restores into fresh PostgreSQL and LocalStack volumes in **60–65
seconds**. The local recovery-time objective (RTO) is **5 minutes**, leaving margin
for workstation and image-startup variation. Rehearse after material schema or
storage changes.

AWS RPO/RTO, managed backups, cross-region recovery, and production key recovery are
unvalidated and deferred to the cloud disaster-recovery work.

## What is included

- PostgreSQL custom-format dump, including schema version and ownership.
- Every object in the configured `S3_DOCUMENT_BUCKET`.
- A versioned inventory manifest and SHA-256 checksums.

Environment files, credentials, access tokens, raw model prompts, Keycloak state,
Redis cache entries, SQS messages, and telemetry are not included. Recreate
infrastructure and identity-provider configuration before restoring application data.

## Create a backup

Start and verify the stack, then choose a new ignored destination:

```bash
make stack-up
make stack-check
make backup-local BACKUP_DIR=artifacts/backups/$(date +%Y%m%d-%H%M%S)
```

The command refuses to overwrite an existing directory and writes files with
restrictive permissions. Copy the completed directory to an access-controlled
location if it must survive loss of the workstation.

## Restore

Restore is destructive for the configured application database and document bucket.
Confirm the exact environment and backup directory first:

```bash
make stack-status
make restore-local \
  RESTORE_DIR=artifacts/backups/20260825-090000 \
  CONFIRM=restore
```

The command verifies the manifest and checksums, stops application services, restores
PostgreSQL and S3, applies pending migrations, restarts the services, and runs the
stack health contract. A missing confirmation or checksum mismatch fails before data
is changed.

## Verify recovery

```bash
make stack-check
make stack-status
```

Then sign in and confirm that an agreement, its original document, analysis artifacts,
and audit timeline are readable. Record the backup timestamp, start/end time, operator,
verification result, and any errors in the incident record. Never paste secrets or raw
agreement text into that record.

## Destructive rehearsal

The automated rehearsal creates its own Compose project, ports, database volume, and
LocalStack volume. It never uses the normal development project:

```bash
BACKUP_RESTORE_LIVE=1 tests/operations/test-backup-restore.sh
```

The rehearsal seeds synthetic database and object-store markers, backs them up,
destroys only the disposable project, restores into fresh volumes, and verifies both
markers and complete stack health.
