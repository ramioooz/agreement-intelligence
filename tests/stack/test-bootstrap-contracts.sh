#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

env_file=$(mktemp)
bootstrap_log=$(mktemp)
project_name="agreement-intelligence-bootstrap-test-$$"
cleanup() {
  docker compose --project-name "$project_name" \
    --env-file "$env_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file" "$bootstrap_log"
}
trap cleanup EXIT INT TERM

sed 's/change-me/test-only-value/g' .env.example >"$env_file"
compose() {
  docker compose --project-name "$project_name" \
    --env-file "$env_file" "$@"
}

run_bootstrap() {
  compose run -T --rm --no-deps "$1" "$2" </dev/null
}

expect_verify_failure() {
  service=$1
  drift=$2
  if run_bootstrap "$service" verify >/dev/null 2>&1; then
    echo "$service verify unexpectedly accepted $drift"
    exit 1
  fi
  echo "$service rejected $drift"
}

aws_local() {
  compose run -T --rm --no-deps \
    --entrypoint awslocal \
    localstack-bootstrap \
    --endpoint-url http://localstack:4566 \
    "$@" </dev/null
}

keycloak_admin() {
  compose exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@" </dev/null
}

for script in \
  docker/localstack/bootstrap.sh \
  docker/keycloak/bootstrap.sh; do
  test -x "$script" || {
    echo "Missing executable $script"
    exit 1
  }
done

test -f docker/keycloak/realm/agreement-intelligence-realm.json

for script in \
  docker/localstack/bootstrap.sh \
  docker/keycloak/bootstrap.sh; do
  for args in "" "invalid" "apply extra"; do
    # Invalid invocations must be rejected before any environment or network use.
    if "$script" $args >/dev/null 2>&1; then
      echo "$script unexpectedly accepted arguments: $args"
      exit 1
    fi
  done
done

compose config --services | grep -qx localstack-bootstrap
compose config --services | grep -qx keycloak-bootstrap

compose up --detach --wait postgres localstack keycloak
if ! compose up localstack-bootstrap keycloak-bootstrap \
  >"$bootstrap_log" 2>&1; then
  sed -n '1,240p' "$bootstrap_log"
  exit 1
fi

for prohibited in \
  test-only-value \
  local-admin \
  access_token; do
  if grep -Fq "$prohibited" "$bootstrap_log"; then
    echo "Bootstrap logs exposed prohibited credential material"
    exit 1
  fi
done

for service in localstack-bootstrap keycloak-bootstrap; do
  container_id=$(compose ps --all --quiet "$service")
  test -n "$container_id"
  test "$(docker inspect --format '{{.State.ExitCode}}' "$container_id")" -eq 0
done

run_bootstrap localstack-bootstrap verify
run_bootstrap keycloak-bootstrap verify

# A second complete apply must converge without duplicate-resource failures.
run_bootstrap localstack-bootstrap apply
run_bootstrap keycloak-bootstrap apply
run_bootstrap localstack-bootstrap verify
run_bootstrap keycloak-bootstrap verify

# A DLQ must never retain a redrive policy. Verification catches the drift and
# apply removes it before restoring the exact three primary policies.
processing_dlq_url=$(aws_local sqs get-queue-url \
  --queue-name agreement-intelligence-agreement-processing-dlq \
  --query QueueUrl \
  --output text)
export_dlq_url=$(aws_local sqs get-queue-url \
  --queue-name agreement-intelligence-exports-dlq \
  --query QueueUrl \
  --output text)
export_dlq_arn=$(aws_local sqs get-queue-attributes \
  --queue-url "$export_dlq_url" \
  --attribute-names QueueArn \
  --query Attributes.QueueArn \
  --output text)
dlq_attributes=$(python3 - "$export_dlq_arn" <<'PY'
import json
import sys

policy = json.dumps({
    "deadLetterTargetArn": sys.argv[1],
    "maxReceiveCount": "2",
})
print(json.dumps({"RedrivePolicy": policy}))
PY
)
aws_local sqs set-queue-attributes \
  --queue-url "$processing_dlq_url" \
  --attributes "$dlq_attributes" \
  >/dev/null
expect_verify_failure localstack-bootstrap "DLQ redrive-policy drift"
run_bootstrap localstack-bootstrap apply
run_bootstrap localstack-bootstrap verify

# LocalStack is a dedicated ephemeral emulator, so apply must remove queues
# outside the exact approved six rather than leaving its own verify contract
# unsatisfied.
aws_local sqs create-queue \
  --queue-name agreement-intelligence-unexpected \
  >/dev/null
expect_verify_failure localstack-bootstrap "unexpected seventh queue drift"
run_bootstrap localstack-bootstrap apply
run_bootstrap localstack-bootstrap verify

# Use the existing bootstrap-admin session only to introduce controlled drift.
# The bootstrap's password checks use separate temporary credential files.
compose exec -T keycloak /bin/sh -eu -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://127.0.0.1:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1' \
  </dev/null

client_uuid=$(keycloak_admin get clients \
  -r agreement-intelligence \
  -q exact=true \
  -q clientId=agreement-intelligence-web \
  --fields id \
  --format csv \
  --noquotes)
keycloak_admin update "clients/$client_uuid" \
  -r agreement-intelligence \
  -s 'name=Drifted Client' \
  -s 'defaultClientScopes=["profile"]' \
  -s 'optionalClientScopes=["phone"]' \
  -s 'attributes={"post.logout.redirect.uris":"http://localhost:3000/*","pkce.code.challenge.method":"S256","unexpected.security.attribute":"true"}' \
  >/dev/null
expect_verify_failure keycloak-bootstrap "client configuration drift"
run_bootstrap keycloak-bootstrap apply
run_bootstrap keycloak-bootstrap verify

# Escaped quotes are valid in JSON object keys. Verification must count this as
# a fifth attribute, and apply must remove it without evaluating key text.
keycloak_admin update "clients/$client_uuid" \
  -r agreement-intelligence \
  -s 'attributes={"post.logout.redirect.uris":"http://localhost:3000/*","pkce.code.challenge.method":"S256","unexpected\"key":"true"}' \
  >/dev/null
expect_verify_failure keycloak-bootstrap "escaped-quote client attribute drift"
run_bootstrap keycloak-bootstrap apply
run_bootstrap keycloak-bootstrap verify

mutated_password="invalid-$project_name"
for username in legal.reviewer platform.admin; do
  user_uuid=$(keycloak_admin get users \
    -r agreement-intelligence \
    -q exact=true \
    -q username="$username" \
    --fields id \
    --format csv \
    --noquotes)
  keycloak_admin set-password \
    -r agreement-intelligence \
    --userid "$user_uuid" \
    --new-password "$mutated_password" \
    --temporary=false \
    >/dev/null 2>&1
  expect_verify_failure keycloak-bootstrap "demo password drift"
  run_bootstrap keycloak-bootstrap apply
  run_bootstrap keycloak-bootstrap verify
done
