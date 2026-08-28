#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

stack_env_file=${STACK_ENV_FILE:-.env}
stack_project_name=${STACK_PROJECT_NAME:-agreement-intelligence}
organization_id=cccccccc-cccc-4ccc-8ccc-cccccccccccc
workspace_id=dddddddd-dddd-4ddd-8ddd-dddddddddddd
agreement_id=eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee
retrieval_build_id=ffffffff-ffff-4fff-8fff-ffffffffffff
citation_id=citation-foreign-mqa-001
policy_id=11111111-1111-4111-8111-111111111111
policy_version_id=22222222-2222-4222-8222-222222222222
review_id=33333333-3333-4333-8333-333333333333
workflow_id=44444444-4444-4444-8444-444444444444
checkpoint_id=55555555-5555-4555-8555-555555555555
package_id=66666666-6666-4666-8666-666666666666
actor_id=77777777-7777-4777-8777-777777777777

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
      --set agreement_id="$agreement_id" \
      --set retrieval_build_id="$retrieval_build_id" \
      --set citation_id="$citation_id" \
      --set policy_id="$policy_id" \
      --set policy_version_id="$policy_version_id" \
      --set review_id="$review_id" \
      --set workflow_id="$workflow_id" \
      --set checkpoint_id="$checkpoint_id" \
      --set package_id="$package_id" \
      --set actor_id="$actor_id" <<'SQL'
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
INSERT INTO retrieval_index_builds (
  id, organization_id, workspace_id, agreement_id, source_checksum,
  chunker_version, state, activated_at
)
VALUES (
  :'retrieval_build_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  :'agreement_id'::uuid,
  repeat('a', 64),
  'manual-qa-v1',
  'active',
  CURRENT_TIMESTAMP
)
ON CONFLICT (id) DO NOTHING;
INSERT INTO retrieval_chunks (
  chunk_id, organization_id, workspace_id, agreement_id, build_id,
  source_checksum, chunker_version, ordinal, heading_path, anchor_ids, content
)
VALUES (
  :'citation_id',
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  :'agreement_id'::uuid,
  :'retrieval_build_id'::uuid,
  repeat('a', 64),
  'manual-qa-v1',
  0,
  '["Synthetic foreign section"]'::json,
  json_build_array(:'citation_id'),
  'Synthetic foreign-scope citation content.'
)
ON CONFLICT (agreement_id, build_id, chunk_id) DO NOTHING;
INSERT INTO approval_policies (
  id, organization_id, workspace_id, name, agreement_family,
  document_direction, jurisdiction, materiality, precedence, created_by
)
VALUES (
  :'policy_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  'Synthetic foreign approval policy',
  'client_agreement',
  'any',
  'any',
  'any',
  100,
  :'actor_id'::uuid
)
ON CONFLICT (id) DO NOTHING;
INSERT INTO approval_policy_versions (
  id, organization_id, workspace_id, policy_id, version, status,
  submitter_may_approve, allow_cross_stage_same_approver, created_by, published_at
)
VALUES (
  :'policy_version_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  :'policy_id'::uuid,
  1,
  'published',
  false,
  false,
  :'actor_id'::uuid,
  CURRENT_TIMESTAMP
)
ON CONFLICT (id) DO NOTHING;
INSERT INTO review_cases (
  id, organization_id, workspace_id, agreement_id, agreement_version_id,
  state, created_by, idempotency_key, revision
)
VALUES (
  :'review_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  :'agreement_id'::uuid,
  NULL,
  'approved',
  :'actor_id'::uuid,
  'synthetic-foreign-review',
  1
)
ON CONFLICT (id) DO NOTHING;
INSERT INTO review_workflows (
  id, organization_id, workspace_id, review_id, policy_version_id,
  checkpoint_id, state, active_stage_ordinal, revision
)
VALUES (
  :'workflow_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  :'review_id'::uuid,
  :'policy_version_id'::uuid,
  :'checkpoint_id'::uuid,
  'approved',
  NULL,
  1
)
ON CONFLICT (id) DO NOTHING;
INSERT INTO review_final_packages (
  id, organization_id, workspace_id, review_id, workflow_id, state,
  manifest_key, pdf_key, manifest_checksum, pdf_checksum
)
VALUES (
  :'package_id'::uuid,
  :'organization_id'::uuid,
  :'workspace_id'::uuid,
  :'review_id'::uuid,
  :'workflow_id'::uuid,
  'approved',
  'manual-qa/foreign-review/manifest.json',
  'manual-qa/foreign-review/package.pdf',
  repeat('b', 64),
  repeat('c', 64)
)
ON CONFLICT (id) DO NOTHING;
COMMIT;
SQL
    printf '%s\n' \
      "organization_id=$organization_id" \
      "workspace_id=$workspace_id" \
      "agreement_id=$agreement_id" \
      "citation_id=$citation_id" \
      "review_id=$review_id" \
      "package_id=$package_id"
    ;;
  second-tenant-cleanup)
    run_sql \
      --set organization_id="$organization_id" \
      --set workspace_id="$workspace_id" \
      --set agreement_id="$agreement_id" \
      --set retrieval_build_id="$retrieval_build_id" \
      --set policy_id="$policy_id" \
      --set policy_version_id="$policy_version_id" \
      --set review_id="$review_id" \
      --set workflow_id="$workflow_id" \
      --set package_id="$package_id" <<'SQL'
BEGIN;
UPDATE agreements
   SET deletion_requested_at = COALESCE(deletion_requested_at, CURRENT_TIMESTAMP)
 WHERE id = :'agreement_id'::uuid
   AND organization_id = :'organization_id'::uuid
   AND workspace_id = :'workspace_id'::uuid;
DELETE FROM review_final_packages WHERE id = :'package_id'::uuid;
DELETE FROM review_workflows WHERE id = :'workflow_id'::uuid;
DELETE FROM review_cases WHERE id = :'review_id'::uuid;
DELETE FROM approval_policy_versions WHERE id = :'policy_version_id'::uuid;
DELETE FROM approval_policies WHERE id = :'policy_id'::uuid;
DELETE FROM retrieval_chunks
 WHERE agreement_id = :'agreement_id'::uuid
   AND build_id = :'retrieval_build_id'::uuid;
DELETE FROM retrieval_index_builds WHERE id = :'retrieval_build_id'::uuid;
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
