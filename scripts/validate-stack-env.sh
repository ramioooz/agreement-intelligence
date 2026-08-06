#!/bin/sh
set -eu

env_file=${1:-${STACK_ENV_FILE:-.env}}

test -f "$env_file" || {
  echo "Missing $env_file. Copy .env.example to .env and replace placeholders."
  exit 1
}

effective_value() {
  variable=$1
  if value=$(printenv "$variable"); then
    printf '%s\n' "$value"
  else
    sed -n "s/^${variable}=//p" "$env_file" | tail -n 1
  fi
}

if test -n "${COMPOSE_PROJECT_NAME:-}" \
  && test "$COMPOSE_PROJECT_NAME" != agreement-intelligence; then
  echo "COMPOSE_PROJECT_NAME must be agreement-intelligence when set."
  exit 1
fi
file_project_name=$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "$env_file" | tail -n 1)
if test -n "$file_project_name" \
  && test "$file_project_name" != agreement-intelligence; then
  echo "COMPOSE_PROJECT_NAME in $env_file must be agreement-intelligence."
  exit 1
fi

required_variables='
POSTGRES_PASSWORD
APP_DB_NAME
APP_DB_USER
APP_DB_PASSWORD
KEYCLOAK_DB_NAME
KEYCLOAK_DB_USER
KEYCLOAK_DB_PASSWORD
KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME
KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD
KEYCLOAK_REALM
OIDC_CLIENT_ID
OIDC_CLIENT_SECRET
OIDC_ISSUER
OIDC_INTERNAL_ISSUER
WEB_PUBLIC_ORIGIN
AUTH_URL
AUTH_SECRET
DEMO_REVIEWER_USERNAME
DEMO_REVIEWER_EMAIL
DEMO_REVIEWER_FIRST_NAME
DEMO_REVIEWER_LAST_NAME
DEMO_REVIEWER_PASSWORD
DEMO_ADMIN_USERNAME
DEMO_ADMIN_EMAIL
DEMO_ADMIN_FIRST_NAME
DEMO_ADMIN_LAST_NAME
DEMO_ADMIN_PASSWORD
DEMO_BUSINESS_APPROVER_USERNAME
DEMO_BUSINESS_APPROVER_EMAIL
DEMO_BUSINESS_APPROVER_FIRST_NAME
DEMO_BUSINESS_APPROVER_LAST_NAME
DEMO_BUSINESS_APPROVER_PASSWORD
AWS_REGION
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
S3_DOCUMENT_BUCKET
SQS_PROCESSING_QUEUE
SQS_PROCESSING_DLQ
SQS_EXPORT_QUEUE
SQS_EXPORT_DLQ
SQS_NOTIFICATION_QUEUE
SQS_NOTIFICATION_DLQ
POSTGRES_PORT
KEYCLOAK_PORT
LOCALSTACK_PORT
WEB_PORT
API_PORT
'

for variable in $required_variables; do
  value=$(effective_value "$variable")
  test -n "$value" || {
    echo "Missing required value: $variable"
    exit 1
  }
  case "$value" in
    *change-me*)
      echo "Replace placeholder value: $variable"
      exit 1
      ;;
  esac
done

for variable in APP_DB_NAME APP_DB_USER KEYCLOAK_DB_NAME KEYCLOAK_DB_USER; do
  value=$(effective_value "$variable")
  printf '%s\n' "$value" | grep -Eq '^[a-z][a-z0-9_]*$' || {
    echo "$variable must use lowercase letters, digits, and underscores."
    exit 1
  }
done

app_db_name=$(effective_value APP_DB_NAME)
keycloak_db_name=$(effective_value KEYCLOAK_DB_NAME)
app_db_user=$(effective_value APP_DB_USER)
keycloak_db_user=$(effective_value KEYCLOAK_DB_USER)

test "$app_db_name" != "$keycloak_db_name" || {
  echo "APP_DB_NAME and KEYCLOAK_DB_NAME must be different."
  exit 1
}

test "$app_db_user" != "$keycloak_db_user" || {
  echo "APP_DB_USER and KEYCLOAK_DB_USER must be different."
  exit 1
}

for variable in APP_DB_NAME KEYCLOAK_DB_NAME; do
  value=$(effective_value "$variable")
  case "$value" in
    template0|template1)
      echo "$variable must not use a PostgreSQL template database."
      exit 1
      ;;
  esac
done

for variable in APP_DB_NAME KEYCLOAK_DB_NAME APP_DB_USER KEYCLOAK_DB_USER; do
  value=$(effective_value "$variable")
  test "$value" != postgres || {
    echo "$variable must not use the reserved PostgreSQL bootstrap identifier."
    exit 1
  }
done

port_variables='POSTGRES_PORT KEYCLOAK_PORT LOCALSTACK_PORT WEB_PORT API_PORT'
ports=
for variable in $port_variables; do
  value=$(effective_value "$variable")
  printf '%s\n' "$value" | grep -Eq '^[0-9]+$' || {
    echo "$variable must be an integer from 1 through 65535."
    exit 1
  }
  test "$value" -ge 1 && test "$value" -le 65535 || {
    echo "$variable must be an integer from 1 through 65535."
    exit 1
  }
  ports="${ports}${value}
"
done

test "$(printf '%s\n' "$ports" | sort | uniq -d | wc -l | tr -d ' ')" -eq 0 || {
  echo "Local ports must be unique."
  exit 1
}

for variable in APP_DB_PASSWORD KEYCLOAK_DB_PASSWORD; do
  value=$(effective_value "$variable")
  printf '%s\n' "$value" | grep -Eq '^[A-Za-z0-9._~-]+$' || {
    echo "$variable must contain only URI-safe letters, digits, ., _, ~, and -."
    exit 1
  }
done

for variable in OIDC_ISSUER OIDC_INTERNAL_ISSUER AUTH_URL; do
  value=$(effective_value "$variable")
  case "$value" in
    http://* | https://*) ;;
    *)
      echo "$variable must be an HTTP(S) URL."
      exit 1
      ;;
  esac
  case "$value" in
    */)
      echo "$variable must not end with a trailing slash."
      exit 1
      ;;
  esac
done

web_public_origin=$(effective_value WEB_PUBLIC_ORIGIN)
printf '%s\n' "$web_public_origin" | grep -Eq '^https?://[^/:?#]+(:[0-9]+)?$' || {
  echo "WEB_PUBLIC_ORIGIN must be an HTTP(S) origin without a path or trailing slash."
  exit 1
}

web_origin_port=$(printf '%s\n' "$web_public_origin" \
  | sed -nE 's#^https?://[^/:?#]+:([0-9]+)$#\1#p')
if test -z "$web_origin_port"; then
  case "$web_public_origin" in
    http://*) web_origin_port=80 ;;
    https://*) web_origin_port=443 ;;
  esac
fi

test "$web_origin_port" = "$(effective_value WEB_PORT)" || {
  echo "WEB_PUBLIC_ORIGIN port must match WEB_PORT."
  exit 1
}
