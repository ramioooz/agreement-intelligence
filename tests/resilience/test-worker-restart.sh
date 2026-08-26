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
$compose run --rm -T --no-deps worker python - <<'PY'
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
jobs = (
    (
        UUID("11111111-1111-4111-8111-111111111111"),
        UUID("21111111-1111-4111-8111-111111111111"),
        "resilience-worker-restart",
        "Synthetic restart agreement",
    ),
    (
        UUID("31111111-1111-4111-8111-111111111111"),
        UUID("41111111-1111-4111-8111-111111111111"),
        "resilience-provider-outage",
        "Synthetic provider outage agreement",
    ),
)
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
    for job_id, agreement_id, idempotency_key, title in jobs:
        storage_key = f"resilience/worker-restart/{agreement_id}.docx"
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
                "title": title,
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
                "idempotency_key": idempotency_key,
                "storage_key": storage_key,
                "checksum": checksum,
                "now": now,
            },
        )
PY
$compose up --detach --no-deps worker
$compose stop worker
app_db=$(sed -n 's/^APP_DB_NAME=//p' "$env_file")
restart_started=$(date +%s)
$compose up --detach --no-deps worker >/dev/null
while ! $compose logs --no-color worker 2>/dev/null | grep -q 'worker.started'; do
  [ $(( $(date +%s) - restart_started )) -lt 60 ] || {
    echo "Worker did not become ready after restart." >&2
    exit 1
  }
  sleep 1
done
$compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
  "UPDATE processing_jobs SET queued_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
    WHERE id = '11111111-1111-4111-8111-111111111111';" >/dev/null
queue_url=$($compose exec -T localstack awslocal sqs get-queue-url --queue-name agreement-intelligence-agreement-processing --query QueueUrl --output text)
body='{"job_id":"11111111-1111-4111-8111-111111111111","organization_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","workspace_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}'
$compose exec -T localstack awslocal sqs send-message --queue-url "$queue_url" --message-body "$body" >/dev/null
$compose exec -T localstack awslocal sqs send-message --queue-url "$queue_url" --message-body "$body" >/dev/null
started=$(date +%s)
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
processing_recovery=$(( $(date +%s) - started ))
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

workflow_seed=$($compose run --rm -T --no-deps api python - <<'PY' | tail -n 1
from datetime import UTC, datetime
from uuid import uuid4

import agreement_intelligence_api.playbooks.models  # noqa: F401
import agreement_intelligence_api.processing.models  # noqa: F401
from agreement_intelligence_api.agreements.models import AgreementRecord
from agreement_intelligence_api.approval_policies.models import (
    ApprovalPolicyRecord,
    ApprovalPolicyStageRecord,
    ApprovalPolicyVersionRecord,
)
from agreement_intelligence_api.db import engine
from agreement_intelligence_api.identity.permissions import RoleKey
from agreement_intelligence_api.identity.service import IdentityService
from agreement_intelligence_api.reviews.models import (
    ReviewAssignmentRecord,
    ReviewCaseRecord,
    ReviewFinalPackageRecord,
    ReviewNotificationEventRecord,
    ReviewWorkflowOutboxRecord,
    ReviewWorkflowRecord,
)
from agreement_intelligence_api.reviews.workflow import ReviewWorkflowCoordinator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

session = Session(engine())
try:
    identity = IdentityService(session)
    identity.bootstrap_authorization_catalog()
    organization = identity.create_organization(
        name="Resilience organization", slug=f"resilience-{uuid4()}"
    )
    workspace = identity.create_workspace(
        organization_id=organization.id,
        name="Resilience workspace",
        slug=f"resilience-{uuid4()}",
    )
    user = identity.provision_user(
        issuer="https://identity.example/resilience",
        subject=f"legal-admin-{uuid4()}",
        display_name="Resilience legal admin",
    )
    membership = identity.grant_membership(
        organization_id=organization.id,
        user_id=user.id,
        role_key=RoleKey.LEGAL_ADMIN,
    )
    identity.grant_workspace_membership(
        organization_id=organization.id,
        membership_id=membership.id,
        workspace_id=workspace.id,
    )
    now = datetime.now(UTC)
    agreement = AgreementRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        title="Synthetic workflow agreement",
        agreement_type="client_agreement",
        status="draft",
        parties=[],
        files=[],
        processing_state="completed",
        audit_metadata={},
        audit_events=[],
        created_at=now,
        updated_at=now,
    )
    session.add(agreement)
    session.flush()
    review = ReviewCaseRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        agreement_id=agreement.id,
        agreement_version_id=None,
        state="open",
        created_by=user.id,
        idempotency_key="resilience-workflow-review",
        revision=0,
        created_at=now,
        updated_at=now,
    )
    policy = ApprovalPolicyRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        name="Resilience approval",
        agreement_family="client_agreement",
        document_direction="any",
        jurisdiction="any",
        materiality="any",
        precedence=100,
        created_by=user.id,
    )
    session.add_all([review, policy])
    session.flush()
    version = ApprovalPolicyVersionRecord(
        organization_id=organization.id,
        workspace_id=workspace.id,
        policy_id=policy.id,
        version=1,
        status="published",
        submitter_may_approve=False,
        allow_cross_stage_same_approver=False,
        created_by=user.id,
        published_at=now,
    )
    session.add(version)
    session.flush()
    session.add(
        ApprovalPolicyStageRecord(
            organization_id=organization.id,
            workspace_id=workspace.id,
            policy_version_id=version.id,
            ordinal=1,
            name="Legal review",
            approval_mode="any",
            quorum_count=None,
            eligible_role_keys=["legal_admin"],
            eligible_user_ids=[],
            deadline_hours=None,
            escalation_role_key=None,
        )
    )
    organization_id = organization.id
    workspace_id = workspace.id
    review_id = review.id
    policy_version_id = version.id
    user_id = user.id
    session.commit()
    identity.scope_organization(organization_id)
    coordinator = ReviewWorkflowCoordinator(session)
    snapshot = coordinator.start(
        review_id=review_id,
        policy_version_id=policy_version_id,
        correlation_id="resilience-workflow-start",
    )
    coordinator.decide(
        workflow_id=snapshot.id,
        actor_id=user_id,
        action="reject",
        idempotency_key="resilience-workflow-reject",
        expected_revision=snapshot.revision,
        correlation_id="resilience-workflow-reject",
    )
    workflow = session.get(ReviewWorkflowRecord, snapshot.id)
    assert workflow is not None
    review = session.get(ReviewCaseRecord, review_id)
    assert review is not None
    terminal_event = session.scalar(
        select(ReviewWorkflowOutboxRecord)
        .where(ReviewWorkflowOutboxRecord.workflow_id == workflow.id)
        .where(ReviewWorkflowOutboxRecord.event_type == "review.workflow.terminal")
    )
    assert terminal_event is not None
    assignment_count = session.scalar(
        select(func.count()).select_from(ReviewAssignmentRecord).where(
            ReviewAssignmentRecord.review_id == review.id
        )
    )
    notification_count = session.scalar(
        select(func.count()).select_from(ReviewNotificationEventRecord).where(
            ReviewNotificationEventRecord.review_id == review.id
        )
    )
    package_count = session.scalar(
        select(func.count()).select_from(ReviewFinalPackageRecord).where(
            ReviewFinalPackageRecord.review_id == review.id
        )
    )
    print(
        "|".join(
            (
                str(workflow.id),
                str(terminal_event.id),
                str(organization_id),
                str(workspace_id),
                str(review_id),
                str(assignment_count),
                str(notification_count),
                str(package_count),
            )
        )
    )
finally:
    session.close()
PY
)
IFS='|' read -r workflow_id workflow_event_id workflow_organization_id workflow_workspace_id \
  workflow_review_id workflow_assignments workflow_notifications workflow_packages <<EOF
$workflow_seed
EOF
[ "$workflow_assignments" = "1" ] && [ "$workflow_notifications" = "1" ] && \
  [ "$workflow_packages" = "0" ] || {
  echo "Workflow seed created package state before terminal worker delivery: $workflow_seed" >&2
  exit 1
}
workflow_queue_name=$(sed -n 's/^SQS_NOTIFICATION_QUEUE=//p' "$env_file")
workflow_queue_url=$($compose exec -T localstack awslocal sqs get-queue-url \
  --queue-name "$workflow_queue_name" --query QueueUrl --output text)
workflow_body=$(printf \
  '{"kind":"review-workflow","event_id":"%s","organization_id":"%s","workspace_id":"%s"}' \
  "$workflow_event_id" "$workflow_organization_id" "$workflow_workspace_id")
$compose exec -T localstack awslocal sqs send-message \
  --queue-url "$workflow_queue_url" --message-body "$workflow_body" >/dev/null
workflow_started=$(date +%s)
while :; do
  processed=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
    "SELECT processed_at IS NOT NULL FROM review_workflow_outbox WHERE id = '$workflow_event_id';")
  [ "$processed" = "t" ] && break
  [ $(( $(date +%s) - workflow_started )) -lt 60 ] || {
    echo "Worker did not checkpoint the workflow event." >&2
    exit 1
  }
  sleep 1
done
checkpoint_count=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
  "SELECT COUNT(*) FROM checkpoints WHERE thread_id = 'review-workflow-event:$workflow_event_id';")
[ "$checkpoint_count" -gt 0 ] || {
  echo "Workflow event did not persist a PostgreSQL LangGraph checkpoint." >&2
  exit 1
}
package_result=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -F '|' -c \
  "SELECT manifest_key, pdf_key, manifest_checksum, pdf_checksum
     FROM review_final_packages WHERE review_id = '$workflow_review_id';")
IFS='|' read -r manifest_key pdf_key manifest_checksum pdf_checksum <<EOF
$package_result
EOF
[ -n "$manifest_key" ] && [ -n "$pdf_key" ] || {
  echo "Terminal workflow event did not create durable package metadata." >&2
  exit 1
}
$compose run --rm -T --no-deps \
  -e RESILIENCE_MANIFEST_KEY="$manifest_key" \
  -e RESILIENCE_PDF_KEY="$pdf_key" \
  -e RESILIENCE_MANIFEST_CHECKSUM="$manifest_checksum" \
  -e RESILIENCE_PDF_CHECKSUM="$pdf_checksum" \
  worker python - <<'PY'
import hashlib
import os

import boto3

client = boto3.client(
    "s3",
    endpoint_url=os.environ["AWS_ENDPOINT_URL"],
    region_name=os.environ["AWS_REGION"],
)
for key_name, checksum_name in (
    ("RESILIENCE_MANIFEST_KEY", "RESILIENCE_MANIFEST_CHECKSUM"),
    ("RESILIENCE_PDF_KEY", "RESILIENCE_PDF_CHECKSUM"),
):
    body = client.get_object(
        Bucket=os.environ["S3_DOCUMENT_BUCKET"], Key=os.environ[key_name]
    )["Body"].read()
    assert hashlib.sha256(body).hexdigest() == os.environ[checksum_name]
PY
$compose exec -T localstack awslocal sqs send-message \
  --queue-url "$workflow_queue_url" --message-body "$workflow_body" >/dev/null
duplicate_started=$(date +%s)
while :; do
  queue_counts=$($compose exec -T localstack awslocal sqs get-queue-attributes \
    --queue-url "$workflow_queue_url" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible]' \
    --output text)
  [ "$queue_counts" = "0	0" ] && break
  [ $(( $(date +%s) - duplicate_started )) -lt 60 ] || {
    echo "Duplicate workflow message was not acknowledged." >&2
    exit 1
  }
  sleep 1
done
durable_counts=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -F '|' -c \
  "SELECT
      (SELECT COUNT(*) FROM review_assignments WHERE review_id = '$workflow_review_id'),
      (SELECT COUNT(*) FROM review_notification_events WHERE review_id = '$workflow_review_id'),
      (SELECT COUNT(*) FROM review_final_packages WHERE review_id = '$workflow_review_id'),
      (SELECT COUNT(*) FROM checkpoints WHERE thread_id = 'review-workflow-event:$workflow_event_id');")
IFS='|' read -r duplicate_assignments duplicate_notifications duplicate_packages \
  duplicate_checkpoints <<EOF
$durable_counts
EOF
[ "$duplicate_assignments" = "$workflow_assignments" ] && \
  [ "$duplicate_notifications" = "$workflow_notifications" ] && \
  [ "$duplicate_packages" = "1" ] && \
  [ "$duplicate_checkpoints" = "$checkpoint_count" ] || {
  echo "Duplicate workflow delivery changed durable state: before=$workflow_seed after=$durable_counts" >&2
  exit 1
}

$compose stop worker >/dev/null
failure_body='{"job_id":"31111111-1111-4111-8111-111111111111","organization_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","workspace_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}'
$compose exec -T localstack awslocal sqs send-message \
  --queue-url "$queue_url" --message-body "$failure_body" >/dev/null
$compose run --detach --no-deps \
  -e OPENAI_API_KEY= \
  -e MODEL_GATEWAY_MODE=openai-compatible \
  -e MODEL_GATEWAY_MODEL=unavailable-resilience-model \
  -e MODEL_GATEWAY_BASE_URL=http://127.0.0.1:9/v1 \
  -e MODEL_GATEWAY_API_KEY=resilience-test-key \
  worker >/dev/null
failure_started=$(date +%s)
while :; do
  failure_state=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -c \
    "SELECT state FROM processing_jobs WHERE id = '31111111-1111-4111-8111-111111111111';")
  [ "$failure_state" = "failed" ] && break
  [ $(( $(date +%s) - failure_started )) -lt 120 ] || {
    echo "Provider-unavailable job did not exhaust its bounded retries." >&2
    exit 1
  }
  sleep 1
done
failure_result=$($compose exec -T postgres psql -U postgres -d "$app_db" -At -F '|' -c \
  "SELECT state, attempt_count, failure_category, failed_at IS NOT NULL,
          (SELECT COUNT(*) FROM processing_artifacts WHERE job_id = processing_jobs.id)
     FROM processing_jobs
    WHERE id = '31111111-1111-4111-8111-111111111111';")
[ "$failure_result" = "failed|3|transient_exhausted|t|0" ] || {
  echo "Provider-unavailable retry state is not durably exhausted: $failure_result" >&2
  exit 1
}
failure_object_count=$($compose exec -T localstack awslocal s3api list-objects-v2 \
  --bucket "$bucket" \
  --prefix "tenants/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/workspaces/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/agreements/41111111-1111-4111-8111-111111111111/analysis/" \
  --query 'length(Contents || `[]`)' --output text)
[ "$failure_object_count" = "0" ] || {
  echo "Provider-unavailable job unexpectedly wrote an analysis object." >&2
  exit 1
}

echo "Worker recovery: restart_ready=$(( started - restart_started ))s job=completed artifact=stored queue_to_processing_start=${queue_to_start}s processing_recovery=${processing_recovery}s."
echo "Duplicate delivery: processing_artifacts=1 workflow_assignments=$duplicate_assignments workflow_notifications=$duplicate_notifications final_packages=$duplicate_packages checkpoints=$duplicate_checkpoints."
echo "Provider outage: state=failed attempts=3 category=transient_exhausted artifacts=0."
