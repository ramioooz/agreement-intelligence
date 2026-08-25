#!/bin/sh
set -eu

[ "${RESILIENCE_TEST_CONFIRM:-}" = "isolated" ] || {
  echo "Set RESILIENCE_TEST_CONFIRM=isolated." >&2
  exit 1
}

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
project="ai-resilience-worker-$$"
env_file=$(mktemp "${TMPDIR:-/tmp}/ai-resilience-worker.XXXXXX")
base=$((20000 + ($$ % 10000)))
cleanup() {
  docker compose --project-name "$project" --env-file "$env_file" -f "$repo_root/compose.yaml" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file"
}
trap cleanup EXIT INT TERM

sed \
  -e 's/change-me-/test-/' \
  -e "s/^POSTGRES_PORT=.*/POSTGRES_PORT=$base/" \
  -e "s/^KEYCLOAK_PORT=.*/KEYCLOAK_PORT=$((base + 1))/" \
  -e "s#^OIDC_ISSUER=.*#OIDC_ISSUER=http://localhost:$((base + 1))/realms/agreement-intelligence#" \
  -e "s/^LOCALSTACK_PORT=.*/LOCALSTACK_PORT=$((base + 2))/" \
  -e "s/^REDIS_PORT=.*/REDIS_PORT=$((base + 3))/" \
  -e "s/^OTEL_GRPC_PORT=.*/OTEL_GRPC_PORT=$((base + 4))/" \
  -e "s/^OTEL_HTTP_PORT=.*/OTEL_HTTP_PORT=$((base + 5))/" \
  -e "s/^WEB_PORT=.*/WEB_PORT=$((base + 6))/" \
  -e "s/^API_PORT=.*/API_PORT=$((base + 7))/" \
  -e "s#^WEB_PUBLIC_ORIGIN=.*#WEB_PUBLIC_ORIGIN=http://localhost:$((base + 6))#" \
  -e "s#^AUTH_URL=.*#AUTH_URL=http://localhost:$((base + 6))#" \
  "$repo_root/.env.example" > "$env_file"

compose="docker compose --project-name $project --env-file $env_file -f $repo_root/compose.yaml"
$compose up --detach --wait --wait-timeout 120 postgres localstack otel-collector
$compose run --rm --no-deps localstack-bootstrap >/dev/null
$compose build api worker >/dev/null
$compose run --rm --no-deps api alembic -c apps/api/alembic.ini upgrade head >/dev/null
$compose run --rm -T --no-deps \
  -e RESILIENCE_SEED_JOB_ID=11111111-1111-4111-8111-111111111111 \
  -e RESILIENCE_SEED_AGREEMENT_ID=21111111-1111-4111-8111-111111111111 \
  worker python - <<'PY'
import hashlib
import os
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import boto3
from docx import Document
from sqlalchemy import create_engine, text

organization_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
workspace_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
job_id = UUID(os.environ["RESILIENCE_SEED_JOB_ID"])
agreement_id = UUID(os.environ["RESILIENCE_SEED_AGREEMENT_ID"])
document = Document()
document.add_heading("Synthetic Client Agreement", level=1)
document.add_paragraph("Either party may terminate this agreement with thirty days notice.")
stream = BytesIO()
document.save(stream)
content = stream.getvalue()
checksum = hashlib.sha256(content).hexdigest()
storage_key = f"resilience/worker-restart/{agreement_id}.docx"
boto3.client(
    "s3",
    endpoint_url=os.environ["AWS_ENDPOINT_URL"],
    region_name=os.environ["AWS_REGION"],
).put_object(
    Bucket=os.environ["S3_DOCUMENT_BUCKET"],
    Key=storage_key,
    Body=content,
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
engine = create_engine(
    os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
)
now = datetime.now(UTC)
with engine.begin() as connection:
    connection.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(organization_id)},
    )
    connection.execute(
        text(
            """
            INSERT INTO agreements (
                id, organization_id, workspace_id, title, agreement_type, status,
                parties, files, processing_state, audit_metadata, audit_events,
                archived_at, created_at, updated_at
            ) VALUES (
                :id, :organization_id, :workspace_id, :title, 'client_agreement', 'draft',
                CAST('[]' AS JSON), CAST('[]' AS JSON), 'queued',
                CAST('{"jurisdiction":"ANY","document_direction":"any"}' AS JSON),
                CAST('[]' AS JSON), NULL, :now, :now
            )
            """
        ),
        {
            "id": agreement_id,
            "organization_id": organization_id,
            "workspace_id": workspace_id,
            "title": "Synthetic restart agreement",
            "now": now,
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO processing_jobs (
                id, organization_id, workspace_id, agreement_id, version_id,
                idempotency_key, profile, source_storage_key, source_checksum,
                source_content_type, state, attempt_count, failure_category,
                failure_message, next_retry_at, queued_at, processing_started_at,
                completed_at, failed_at, created_at, updated_at
            ) VALUES (
                :id, :organization_id, :workspace_id, :agreement_id, NULL,
                'resilience-worker-restart', 'default', :storage_key, :checksum,
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'queued', 0, NULL, NULL, NULL, :now, NULL, NULL, NULL, :now, :now
            )
            """
        ),
        {
            "id": job_id,
            "organization_id": organization_id,
            "workspace_id": workspace_id,
            "agreement_id": agreement_id,
            "storage_key": storage_key,
            "checksum": checksum,
            "now": now,
        },
    )
PY
$compose up --detach --no-deps worker
$compose stop worker
app_db=$(sed -n 's/^APP_DB_NAME=//p' "$env_file")
$compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
  "UPDATE processing_jobs SET queued_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
    WHERE id = '11111111-1111-4111-8111-111111111111';" >/dev/null
queue_url=$($compose exec -T localstack awslocal sqs get-queue-url --queue-name agreement-intelligence-agreement-processing --query QueueUrl --output text)
body='{"job_id":"11111111-1111-4111-8111-111111111111","organization_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","workspace_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}'
$compose exec -T localstack awslocal sqs send-message --queue-url "$queue_url" --message-body "$body" >/dev/null
started=$(date +%s)
$compose up --detach --no-deps worker >/dev/null
while :; do
  state=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
    "SELECT state FROM processing_jobs WHERE id = '11111111-1111-4111-8111-111111111111';")
  [ "$state" = "completed" ] && break
  [ "$state" != "failed" ] || {
    failure=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
      "SELECT COALESCE(failure_category, '') || ':' || COALESCE(failure_message, '')
         FROM processing_jobs WHERE id = '11111111-1111-4111-8111-111111111111';")
    echo "Seeded processing job failed: $failure" >&2
    exit 1
  }
  [ $(( $(date +%s) - started )) -lt 60 ] || { echo "Worker did not complete the queued job." >&2; exit 1; }
  sleep 1
done
job_result=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -F '|' -c \
  "SELECT state, processing_started_at IS NOT NULL, completed_at IS NOT NULL,
          (SELECT COUNT(*) FROM processing_artifacts WHERE job_id = processing_jobs.id),
          COALESCE((SELECT artifact_key FROM processing_artifacts WHERE job_id = processing_jobs.id LIMIT 1), ''),
          ROUND(EXTRACT(EPOCH FROM (processing_started_at - queued_at))::numeric, 3)
     FROM processing_jobs
    WHERE id = '11111111-1111-4111-8111-111111111111';")
IFS='|' read -r state has_started has_completed artifact_count artifact_key queue_to_start <<EOF
$job_result
EOF
[ "$state" = "completed" ] && [ "$has_started" = "t" ] && [ "$has_completed" = "t" ] || {
  echo "Worker did not durably complete the seeded processing job: $job_result" >&2
  exit 1
}
[ "$artifact_count" = "1" ] && [ -n "$artifact_key" ] || {
  echo "Worker did not persist exactly one processing artifact: $job_result" >&2
  exit 1
}
bucket=$(sed -n 's/^S3_DOCUMENT_BUCKET=//p' "$env_file")
$compose exec -T localstack awslocal s3api head-object \
  --bucket "$bucket" --key "$artifact_key" >/dev/null
awk -v latency="$queue_to_start" 'BEGIN { exit !(latency < 5) }' || {
  echo "Queue-to-processing-start objective missed: ${queue_to_start}s (limit: 5s)." >&2
  exit 1
}
echo "Worker restart: job=completed artifact=stored queue_to_processing_start=${queue_to_start}s total_recovery=$(( $(date +%s) - started ))s."
