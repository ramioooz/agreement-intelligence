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
  remaining=$($compose exec -T localstack awslocal sqs get-queue-attributes --queue-url "$queue_url" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query 'Attributes.*' --output text | awk '{sum += $1} END {print sum + 0}')
  [ "$remaining" -eq 0 ] && break
  [ $(( $(date +%s) - started )) -lt 60 ] || { echo "Backlog did not drain." >&2; exit 1; }
  sleep 1
done
duration=$(( $(date +%s) - started ))
echo "Queue drained $count messages in $duration seconds; remaining=0."
