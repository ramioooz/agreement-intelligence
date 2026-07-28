#!/bin/sh
set -eu

env_file=${1:-${STACK_ENV_FILE:-.env}}

test -f "$env_file" || {
  echo "Missing $env_file. Copy .env.example to .env and replace placeholders."
  exit 1
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
DEMO_REVIEWER_USERNAME
DEMO_REVIEWER_EMAIL
DEMO_REVIEWER_PASSWORD
DEMO_ADMIN_USERNAME
DEMO_ADMIN_EMAIL
DEMO_ADMIN_PASSWORD
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
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
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
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  printf '%s\n' "$value" | grep -Eq '^[a-z][a-z0-9_]*$' || {
    echo "$variable must use lowercase letters, digits, and underscores."
    exit 1
  }
done

app_db_name=$(sed -n 's/^APP_DB_NAME=//p' "$env_file" | tail -n 1)
keycloak_db_name=$(sed -n 's/^KEYCLOAK_DB_NAME=//p' "$env_file" | tail -n 1)
app_db_user=$(sed -n 's/^APP_DB_USER=//p' "$env_file" | tail -n 1)
keycloak_db_user=$(sed -n 's/^KEYCLOAK_DB_USER=//p' "$env_file" | tail -n 1)

test "$app_db_name" != "$keycloak_db_name" || {
  echo "APP_DB_NAME and KEYCLOAK_DB_NAME must be different."
  exit 1
}

test "$app_db_user" != "$keycloak_db_user" || {
  echo "APP_DB_USER and KEYCLOAK_DB_USER must be different."
  exit 1
}

for variable in APP_DB_NAME KEYCLOAK_DB_NAME APP_DB_USER KEYCLOAK_DB_USER; do
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  test "$value" != postgres || {
    echo "$variable must not use the reserved PostgreSQL bootstrap identifier."
    exit 1
  }
done

port_variables='POSTGRES_PORT KEYCLOAK_PORT LOCALSTACK_PORT WEB_PORT API_PORT'
ports=
for variable in $port_variables; do
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
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
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  printf '%s\n' "$value" | grep -Eq '^[A-Za-z0-9._~-]+$' || {
    echo "$variable must contain only URI-safe letters, digits, ., _, ~, and -."
    exit 1
  }
done
