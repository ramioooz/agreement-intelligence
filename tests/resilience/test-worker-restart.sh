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
$compose up --detach --no-deps worker
$compose stop worker
queue_url=$($compose exec -T localstack awslocal sqs get-queue-url --queue-name agreement-intelligence-agreement-processing --query QueueUrl --output text)
body='{"job_id":"11111111-1111-4111-8111-111111111111","organization_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","workspace_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}'
$compose exec -T localstack awslocal sqs send-message --queue-url "$queue_url" --message-body "$body" >/dev/null
started=$(date +%s)
$compose up --detach --no-deps worker >/dev/null
while :; do
  remaining=$($compose exec -T localstack awslocal sqs get-queue-attributes --queue-url "$queue_url" --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible --query 'Attributes.*' --output text | awk '{sum += $1} END {print sum + 0}')
  [ "$remaining" -eq 0 ] && break
  [ $(( $(date +%s) - started )) -lt 30 ] || { echo "Worker did not drain the queued message." >&2; exit 1; }
  sleep 1
done
echo "Worker recovered and drained the message in $(( $(date +%s) - started )) seconds."
