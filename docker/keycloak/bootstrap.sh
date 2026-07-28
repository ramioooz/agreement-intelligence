#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 apply|verify" >&2
  exit 2
}

test "$#" -eq 1 || usage
action=$1
case "$action" in
  apply | verify) ;;
  *) usage ;;
esac

server=${KEYCLOAK_SERVER_URL:-http://keycloak:8080}
kcadm=/opt/keycloak/bin/kcadm.sh

login() {
  "$kcadm" config credentials \
    --server "$server" \
    --realm master \
    --user "$KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME" \
    --password "$KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD" \
    >/dev/null 2>&1
}

single_id() {
  resource=$1
  shift
  ids=$("$kcadm" get "$resource" "$@" \
    --fields id \
    --format csv \
    --noquotes)
  test -n "$ids" || return 1
  case "$ids" in
    *'
'*) return 1 ;;
  esac
  printf '%s\n' "$ids"
}

client_id() {
  single_id clients \
    -r "$KEYCLOAK_REALM" \
    -q exact=true \
    -q clientId="$OIDC_CLIENT_ID"
}

user_id() {
  single_id users \
    -r "$KEYCLOAK_REALM" \
    -q exact=true \
    -q username="$1"
}

ensure_client() {
  id=$(client_id || true)
  if test -z "$id"; then
    "$kcadm" create clients \
      -r "$KEYCLOAK_REALM" \
      -s clientId="$OIDC_CLIENT_ID" \
      >/dev/null
    id=$(client_id)
  fi

  "$kcadm" update "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    -s 'name=Agreement Intelligence Web' \
    -s enabled=true \
    -s protocol=openid-connect \
    -s clientAuthenticatorType=client-secret \
    -s publicClient=false \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s 'redirectUris=["http://localhost:3000/auth/callback"]' \
    -s 'webOrigins=["http://localhost:3000"]' \
    -s 'attributes={"post.logout.redirect.uris":"http://localhost:3000/*","pkce.code.challenge.method":"S256"}' \
    -s 'defaultClientScopes=["web-origins","acr","roles","profile","email"]' \
    -s 'optionalClientScopes=["address","phone","offline_access","microprofile-jwt"]' \
    -s "secret=$OIDC_CLIENT_SECRET" \
    >/dev/null
}

ensure_user() {
  username=$1
  email=$2
  password=$3
  id=$(user_id "$username" || true)

  if test -z "$id"; then
    "$kcadm" create users \
      -r "$KEYCLOAK_REALM" \
      -s username="$username" \
      -s email="$email" \
      -s enabled=true \
      -s emailVerified=true \
      >/dev/null
    id=$(user_id "$username")
  else
    "$kcadm" update "users/$id" \
      -r "$KEYCLOAK_REALM" \
      -s username="$username" \
      -s email="$email" \
      -s enabled=true \
      -s emailVerified=true \
      >/dev/null
  fi

  "$kcadm" set-password \
    -r "$KEYCLOAK_REALM" \
    --userid "$id" \
    --new-password "$password" \
    --temporary=false \
    >/dev/null
}

assert_json_field() {
  json=$1
  expected=$2
  printf '%s\n' "$json" | grep -Eq "$expected"
}

assert_compact_json() {
  json=$1
  expected=$2
  compact=$(printf '%s' "$json" | tr -d '[:space:]')
  test "$compact" = "$expected"
}

verify_realm() {
  realm_csv=$("$kcadm" get "realms/$KEYCLOAK_REALM" \
    --fields realm,enabled,displayName,registrationAllowed,resetPasswordAllowed,rememberMe,verifyEmail,loginWithEmailAllowed,duplicateEmailsAllowed \
    --format csv \
    --noquotes)
  test "$realm_csv" = \
    "$KEYCLOAK_REALM,true,Agreement Intelligence,false,true,false,false,true,false"
}

verify_client() {
  id=$(client_id)
  client_json=$("$kcadm" get "clients/$id" -r "$KEYCLOAK_REALM")
  client_csv=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields clientId,enabled,protocol,clientAuthenticatorType,publicClient,standardFlowEnabled,implicitFlowEnabled,directAccessGrantsEnabled,serviceAccountsEnabled \
    --format csv \
    --noquotes)
  test "$client_csv" = \
    "$OIDC_CLIENT_ID,true,openid-connect,client-secret,false,true,false,false,false"
  redirect_json=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields redirectUris)
  assert_compact_json \
    "$redirect_json" \
    '{"redirectUris":["http://localhost:3000/auth/callback"]}'
  origins_json=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields webOrigins)
  assert_compact_json \
    "$origins_json" \
    '{"webOrigins":["http://localhost:3000"]}'
  assert_json_field "$client_json" '"post[.]logout[.]redirect[.]uris"[[:space:]]*:[[:space:]]*"http://localhost:3000/\*"'
  assert_json_field "$client_json" '"pkce[.]code[.]challenge[.]method"[[:space:]]*:[[:space:]]*"S256"'

  current_secret=$("$kcadm" get "clients/$id/client-secret" \
    -r "$KEYCLOAK_REALM" \
    --fields value \
    --format csv \
    --noquotes \
    | sed -n '1p')
  test "$current_secret" = "$OIDC_CLIENT_SECRET"
}

verify_user() {
  username=$1
  email=$2
  id=$(user_id "$username")
  user_csv=$("$kcadm" get "users/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields username,email,enabled,emailVerified \
    --format csv \
    --noquotes)
  test "$user_csv" = "$username,$email,true,true"
}

apply() {
  "$kcadm" update "realms/$KEYCLOAK_REALM" \
    -s enabled=true \
    -s 'displayName=Agreement Intelligence' \
    -s registrationAllowed=false \
    -s resetPasswordAllowed=true \
    -s rememberMe=false \
    -s verifyEmail=false \
    -s loginWithEmailAllowed=true \
    -s duplicateEmailsAllowed=false \
    >/dev/null

  ensure_client
  ensure_user \
    "$DEMO_REVIEWER_USERNAME" \
    "$DEMO_REVIEWER_EMAIL" \
    "$DEMO_REVIEWER_PASSWORD"
  ensure_user \
    "$DEMO_ADMIN_USERNAME" \
    "$DEMO_ADMIN_EMAIL" \
    "$DEMO_ADMIN_PASSWORD"
}

verify() {
  verify_realm
  verify_client
  verify_user "$DEMO_REVIEWER_USERNAME" "$DEMO_REVIEWER_EMAIL"
  verify_user "$DEMO_ADMIN_USERNAME" "$DEMO_ADMIN_EMAIL"
}

login
case "$action" in
  apply)
    apply
    verify
    ;;
  verify)
    verify
    ;;
esac
