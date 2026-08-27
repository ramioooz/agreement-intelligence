#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

stack_env_file=${STACK_ENV_FILE:-.env}
stack_project_name=${STACK_PROJECT_NAME:-agreement-intelligence}
organization_id=cccccccc-cccc-4ccc-8ccc-cccccccccccc
workspace_id=dddddddd-dddd-4ddd-8ddd-dddddddddddd
agreement_id=eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee

test -f "$stack_env_file" || {
  echo "Missing $stack_env_file." >&2
  exit 1
}

database_name=$(sed -n 's/^APP_DB_NAME=//p' "$stack_env_file" | tail -n 1)
test -n "$database_name" || {
  echo "APP_DB_NAME is missing from $stack_env_file." >&2
  exit 1
}

run_sql() {
  docker compose --project-name "$stack_project_name" --env-file "$stack_env_file" \
    exec -T postgres psql -X --set ON_ERROR_STOP=1 --username postgres \
      --dbname "$database_name" "$@"
}

require_uuid() {
  case "$1" in
    [0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) ;;
    *) echo "Expected a UUID, received an invalid identifier." >&2; exit 2 ;;
  esac
}

case "${1:-}" in
  second-tenant-setup)
    run_sql \
      --set organization_id="$organization_id" \
      --set workspace_id="$workspace_id" \
      --set agreement_id="$agreement_id" <<'SQL'
BEGIN;
INSERT INTO organizations (id, name, slug)
VALUES (:'organization_id'::uuid, 'Synthetic MQA tenant', 'synthetic-mqa-tenant')
ON CONFLICT (id) DO NOTHING;
INSERT INTO workspaces (id, organization_id, name, slug)
VALUES (
  :'workspace_id'::uuid,
  :'organization_id'::uuid,
  'Synthetic MQA workspace',
  'synthetic-mqa-workspace'
)
ON CONFLICT (organization_id, id) DO NOTHING;
INSERT INTO agreements (
  id, organization_id, workspace_id, title, agreement_type, status, parties,
  files, processing_state, audit_metadata, audit_events
)
VALUES (
  :'agreement_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  'Synthetic foreign-scope agreement',
  'client_agreement',
  'draft',
  '[]'::json,
  '[]'::json,
  'pending',
  '{"source":"manual_qa"}'::json,
  '[]'::json
)
ON CONFLICT (id) DO NOTHING;
COMMIT;
SQL
    printf 'organization_id=%s\nworkspace_id=%s\nagreement_id=%s\n' \
      "$organization_id" "$workspace_id" "$agreement_id"
    ;;
  second-tenant-cleanup)
    run_sql \
      --set organization_id="$organization_id" \
      --set workspace_id="$workspace_id" \
      --set agreement_id="$agreement_id" <<'SQL'
BEGIN;
DELETE FROM agreements WHERE id = :'agreement_id'::uuid;
DELETE FROM workspaces
 WHERE id = :'workspace_id'::uuid
   AND organization_id = :'organization_id'::uuid;
DELETE FROM organizations WHERE id = :'organization_id'::uuid;
COMMIT;
SQL
    echo "Removed only the fixed synthetic MQA tenant fixture."
    ;;
  failed-job-setup)
    test "$#" -eq 3 || {
      echo "Usage: scripts/manual-qa-state.sh failed-job-setup AGREEMENT_UUID JOB_UUID" >&2
      exit 2
    }
    require_uuid "$2"
    require_uuid "$3"
    job_state=$(run_sql --tuples-only --no-align \
      --set agreement_id="$2" --set job_id="$3" <<'SQL'
SELECT state
  FROM processing_jobs
 WHERE id = :'job_id'::uuid
   AND agreement_id = :'agreement_id'::uuid;
SQL
    )
    case "$job_state" in
      queued | processing) ;;
      *)
        echo "No queued/processing job matched the supplied identifiers." >&2
        exit 3
        ;;
    esac
    run_sql --set agreement_id="$2" --set job_id="$3" <<'SQL'
BEGIN;
UPDATE processing_jobs
   SET state = 'failed',
       attempt_count = GREATEST(attempt_count, 1),
       failure_category = 'transient',
       failure_message = 'Synthetic manual-QA recoverable failure.',
       next_retry_at = NULL,
       claim_token = NULL,
       claim_lease_expires_at = NULL,
       failed_at = CURRENT_TIMESTAMP,
       updated_at = CURRENT_TIMESTAMP
 WHERE id = :'job_id'::uuid
   AND agreement_id = :'agreement_id'::uuid
   AND state IN ('queued', 'processing');
UPDATE agreements
   SET processing_state = 'failed', updated_at = CURRENT_TIMESTAMP
 WHERE id = :'agreement_id'::uuid
   AND EXISTS (
     SELECT 1 FROM processing_jobs
      WHERE id = :'job_id'::uuid
        AND agreement_id = :'agreement_id'::uuid
        AND state = 'failed'
   );
UPDATE agreement_versions
   SET processing_state = 'failed'
 WHERE agreement_id = :'agreement_id'::uuid
   AND processing_job_id = :'job_id'::uuid;
COMMIT;
SQL
    echo "Synthetic failure applied. Restore the worker, then use the authorized Retry API request for cleanup."
    ;;
  *)
    echo "Usage: scripts/manual-qa-state.sh {second-tenant-setup|second-tenant-cleanup|failed-job-setup AGREEMENT_UUID JOB_UUID}" >&2
    exit 2
    ;;
esac
