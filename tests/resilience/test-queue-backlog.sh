#!/bin/sh
set -eu

[ "${RESILIENCE_TEST_CONFIRM:-}" = "isolated" ] || {
  echo "Set RESILIENCE_TEST_CONFIRM=isolated." >&2
  exit 1
}

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
project="ai-resilience-backlog-$$"
env_file=$(mktemp "${TMPDIR:-/tmp}/ai-resilience-backlog.XXXXXX")
base=$((31000 + ($$ % 10000)))
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
$compose up --detach --no-deps worker
$compose stop worker
queue_url=$($compose exec -T localstack awslocal sqs get-queue-url --queue-name agreement-intelligence-agreement-processing --query QueueUrl --output text)
count=${RESILIENCE_BACKLOG_SIZE:-20}
[ "$count" -ge 1 ] && [ "$count" -le 100 ] || {
  echo "RESILIENCE_BACKLOG_SIZE must be between 1 and 100." >&2
  exit 1
}
$compose run --rm -T --no-deps -e RESILIENCE_SEED_COUNT="$count" worker python - <<'PY'
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
count = int(os.environ["RESILIENCE_SEED_COUNT"])
document = Document()
document.add_heading("Synthetic Client Agreement", level=1)
document.add_paragraph("Either party may terminate this agreement with thirty days notice.")
stream = BytesIO()
document.save(stream)
content = stream.getvalue()
checksum = hashlib.sha256(content).hexdigest()
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["AWS_ENDPOINT_URL"],
    region_name=os.environ["AWS_REGION"],
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
    for index in range(1, count + 1):
        job_id = UUID(f"00000000-0000-4000-8000-{index:012d}")
        agreement_id = UUID(f"10000000-0000-4000-8000-{index:012d}")
        storage_key = f"resilience/backlog/{agreement_id}.docx"
        s3.put_object(
            Bucket=os.environ["S3_DOCUMENT_BUCKET"],
            Key=storage_key,
            Body=content,
            ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        connection.execute(
            text(
                """
                INSERT INTO agreements (
                    id, organization_id, workspace_id, title, agreement_type, status,
                    parties, files, processing_state, audit_metadata, audit_events,
                    archived_at, created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :workspace_id, :title,
                    'client_agreement', 'draft', CAST('[]' AS JSON), CAST('[]' AS JSON),
                    'queued', CAST('{"jurisdiction":"ANY","document_direction":"any"}' AS JSON),
                    CAST('[]' AS JSON), NULL, :now, :now
                )
                """
            ),
            {
                "id": agreement_id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "title": f"Synthetic backlog agreement {index}",
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
                    :idempotency_key, 'default', :storage_key, :checksum,
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
                "idempotency_key": f"resilience-backlog-{index}",
                "storage_key": storage_key,
                "checksum": checksum,
                "now": now,
            },
        )
PY
app_db=$(sed -n 's/^APP_DB_NAME=//p' "$env_file")
i=1
while [ "$i" -le "$count" ]; do
  job=$(printf '00000000-0000-4000-8000-%012d' "$i")
  body=$(printf '{"job_id":"%s","organization_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","workspace_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}' "$job")
  $compose exec -T localstack awslocal sqs send-message --queue-url "$queue_url" --message-body "$body" >/dev/null
  i=$((i + 1))
done
queued=$($compose exec -T localstack awslocal sqs get-queue-attributes --queue-url "$queue_url" --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text)
[ "$queued" -gt 0 ] || { echo "Synthetic backlog was not visible." >&2; exit 1; }
started=$(date +%s)
$compose up --detach --no-deps worker >/dev/null
while :; do
  completion=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -F '|' -c \
    "SELECT COUNT(*) FILTER (WHERE state = 'completed'),
            COUNT(*) FILTER (WHERE state = 'failed')
       FROM processing_jobs
      WHERE idempotency_key LIKE 'resilience-backlog-%';")
  IFS='|' read -r completed failed <<EOF
$completion
EOF
  [ "$failed" = "0" ] || { echo "A seeded backlog job failed." >&2; exit 1; }
  [ "$completed" -eq "$count" ] && break
  [ $(( $(date +%s) - started )) -lt 120 ] || { echo "Backlog did not complete." >&2; exit 1; }
  sleep 1
done
duration=$(( $(date +%s) - started ))
artifact_count=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
  "SELECT COUNT(*) FROM processing_artifacts artifact
    JOIN processing_jobs job ON job.id = artifact.job_id
   WHERE job.idempotency_key LIKE 'resilience-backlog-%';")
[ "$artifact_count" -eq "$count" ] || {
  echo "Expected $count persisted artifacts, found $artifact_count." >&2
  exit 1
}
bucket=$(sed -n 's/^S3_DOCUMENT_BUCKET=//p' "$env_file")
$compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
  "SELECT artifact.artifact_key FROM processing_artifacts artifact
    JOIN processing_jobs job ON job.id = artifact.job_id
   WHERE job.idempotency_key LIKE 'resilience-backlog-%'
   ORDER BY artifact.artifact_key;" |
while IFS= read -r artifact_key; do
  [ -n "$artifact_key" ] || continue
  $compose exec -T localstack awslocal s3api head-object \
    --bucket "$bucket" --key "$artifact_key" >/dev/null
done
remaining=$($compose exec -T localstack awslocal sqs get-queue-attributes --queue-url "$queue_url" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query 'Attributes.*' --output text | awk '{sum += $1} END {print sum + 0}')
[ "$remaining" -eq 0 ] || { echo "Backlog jobs completed but queue still has $remaining messages." >&2; exit 1; }
max_queue_to_start=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
  "SELECT ROUND(MAX(EXTRACT(EPOCH FROM (processing_started_at - queued_at)))::numeric, 3)
     FROM processing_jobs WHERE idempotency_key LIKE 'resilience-backlog-%';")
throughput=$(awk -v jobs="$count" -v seconds="$duration" \
  'BEGIN { if (seconds == 0) print jobs; else printf "%.3f", jobs / seconds }')
echo "Backlog recovery: jobs=$count completed=$completed artifacts=$artifact_count remaining=0 duration=${duration}s max_queue_to_start=${max_queue_to_start}s observed_throughput=${throughput}_jobs_per_second."
echo "Capacity observation: validated_envelope=${count}_jobs_under_120s bottleneck=single_worker_sequential_processing saturation_ceiling=not_established."
