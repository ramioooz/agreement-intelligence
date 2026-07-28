#!/bin/sh
set -eu

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_db="$APP_DB_NAME" \
  --set=app_user="$APP_DB_USER" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=keycloak_db="$KEYCLOAK_DB_NAME" \
  --set=keycloak_user="$KEYCLOAK_DB_USER" \
  --set=keycloak_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L',
  :'keycloak_user',
  :'keycloak_password'
)
WHERE NOT EXISTS (
  SELECT FROM pg_roles WHERE rolname = :'keycloak_user'
) \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db') \gexec

SELECT format(
  'CREATE DATABASE %I OWNER %I',
  :'keycloak_db',
  :'keycloak_user'
)
WHERE NOT EXISTS (
  SELECT FROM pg_database WHERE datname = :'keycloak_db'
) \gexec
SQL

psql \
  --username "$POSTGRES_USER" \
  --dbname "$APP_DB_NAME" \
  --command 'CREATE EXTENSION IF NOT EXISTS vector;'
