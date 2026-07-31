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
web_public_origin=${WEB_PUBLIC_ORIGIN:-http://localhost:3000}
kcadm=/opt/keycloak/bin/kcadm.sh
client_attributes=/ClientAttributes.java
keycloak_classpath='/opt/keycloak/lib/lib/main/*'
temporary_auth_config=

cleanup_auth_config() {
  if test -n "$temporary_auth_config"; then
    rm -f "$temporary_auth_config"
    temporary_auth_config=
  fi
}

trap cleanup_auth_config EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

clear_client_attributes() {
  id=$1
  update=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields 'clientId,attributes(*)' \
    | java --class-path "$keycloak_classpath" "$client_attributes" clear)
  "$kcadm" update "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --no-merge \
    --body "$update" \
    >/dev/null
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

  clear_client_attributes "$id"
  "$kcadm" update "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --no-merge \
    -s clientId="$OIDC_CLIENT_ID" \
    -s 'name=Agreement Intelligence Web' \
    -s enabled=true \
    -s protocol=openid-connect \
    -s clientAuthenticatorType=client-secret \
    -s publicClient=false \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s "redirectUris=[\"$web_public_origin/api/auth/callback/keycloak\"]" \
    -s "webOrigins=[\"$web_public_origin\"]" \
    -s "attributes={\"post.logout.redirect.uris\":\"$web_public_origin/*\",\"pkce.code.challenge.method\":\"S256\"}" \
    -s 'defaultClientScopes=["web-origins","acr","roles","profile","email"]' \
    -s 'optionalClientScopes=["address","phone","offline_access","microprofile-jwt"]' \
    -s "secret=$OIDC_CLIENT_SECRET" \
    >/dev/null
}

ensure_user() {
  username=$1
  email=$2
  first_name=$3
  last_name=$4
  password=$5
  subject=$6
  id=$(user_id "$username" || true)

  if test -z "$id"; then
    if test -n "$subject"; then
      "$kcadm" create users \
        -r "$KEYCLOAK_REALM" \
        -s id="$subject" \
        -s username="$username" \
        -s email="$email" \
        -s firstName="$first_name" \
        -s lastName="$last_name" \
        -s enabled=true \
        -s emailVerified=true \
        >/dev/null
    else
      "$kcadm" create users \
        -r "$KEYCLOAK_REALM" \
        -s username="$username" \
        -s email="$email" \
        -s firstName="$first_name" \
        -s lastName="$last_name" \
        -s enabled=true \
        -s emailVerified=true \
        >/dev/null
    fi
    id=$(user_id "$username")
  else
    "$kcadm" update "users/$id" \
      -r "$KEYCLOAK_REALM" \
      -s username="$username" \
      -s email="$email" \
      -s firstName="$first_name" \
      -s lastName="$last_name" \
      -s enabled=true \
      -s emailVerified=true \
      >/dev/null
  fi
  test -z "$subject" || test "$id" = "$subject"

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
  client_csv=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields clientId,name,enabled,protocol,clientAuthenticatorType,publicClient,standardFlowEnabled,implicitFlowEnabled,directAccessGrantsEnabled,serviceAccountsEnabled \
    --format csv \
    --noquotes)
  test "$client_csv" = \
    "$OIDC_CLIENT_ID,Agreement Intelligence Web,true,openid-connect,client-secret,false,true,false,false,false"
  redirect_json=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields redirectUris)
  assert_compact_json \
    "$redirect_json" \
    "{\"redirectUris\":[\"$web_public_origin/api/auth/callback/keycloak\"]}"
  origins_json=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields webOrigins)
  assert_compact_json \
    "$origins_json" \
    "{\"webOrigins\":[\"$web_public_origin\"]}"
  attributes_json=$("$kcadm" get "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields 'attributes(*)')
  printf '%s\n' "$attributes_json" \
    | java --class-path "$keycloak_classpath" "$client_attributes" verify

  default_scopes=$("$kcadm" get "clients/$id/default-client-scopes" \
    -r "$KEYCLOAK_REALM" \
    --fields name \
    --format csv \
    --noquotes \
    | sort)
  expected_default_scopes=$(printf '%s\n' \
    web-origins acr roles profile email \
    | sort)
  test "$default_scopes" = "$expected_default_scopes"

  optional_scopes=$("$kcadm" get "clients/$id/optional-client-scopes" \
    -r "$KEYCLOAK_REALM" \
    --fields name \
    --format csv \
    --noquotes \
    | sort)
  expected_optional_scopes=$(printf '%s\n' \
    address phone offline_access microprofile-jwt \
    | sort)
  test "$optional_scopes" = "$expected_optional_scopes"

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
  first_name=$3
  last_name=$4
  password=$5
  id=$(user_id "$username")
  user_csv=$("$kcadm" get "users/$id" \
    -r "$KEYCLOAK_REALM" \
    --fields username,email,firstName,lastName,enabled,emailVerified \
    --format csv \
    --noquotes)
  test "$user_csv" = \
    "$username,$email,$first_name,$last_name,true,true"

  temporary_auth_config=$(mktemp /tmp/kcadm-demo-auth.XXXXXX)
  if "$kcadm" config credentials \
    --config "$temporary_auth_config" \
    --server "$server" \
    --realm "$KEYCLOAK_REALM" \
    --client admin-cli \
    --user "$username" \
    --password "$password" \
    >/dev/null 2>&1; then
    auth_status=0
  else
    auth_status=$?
  fi
  cleanup_auth_config
  return "$auth_status"
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
    "$DEMO_REVIEWER_FIRST_NAME" \
    "$DEMO_REVIEWER_LAST_NAME" \
    "$DEMO_REVIEWER_PASSWORD" \
    "$DEMO_REVIEWER_SUBJECT"
  ensure_user \
    "$DEMO_ADMIN_USERNAME" \
    "$DEMO_ADMIN_EMAIL" \
    "$DEMO_ADMIN_FIRST_NAME" \
    "$DEMO_ADMIN_LAST_NAME" \
    "$DEMO_ADMIN_PASSWORD" \
    ""
}

verify() {
  verify_realm
  verify_client
  verify_user \
    "$DEMO_REVIEWER_USERNAME" \
    "$DEMO_REVIEWER_EMAIL" \
    "$DEMO_REVIEWER_FIRST_NAME" \
    "$DEMO_REVIEWER_LAST_NAME" \
    "$DEMO_REVIEWER_PASSWORD"
  verify_user \
    "$DEMO_ADMIN_USERNAME" \
    "$DEMO_ADMIN_EMAIL" \
    "$DEMO_ADMIN_FIRST_NAME" \
    "$DEMO_ADMIN_LAST_NAME" \
    "$DEMO_ADMIN_PASSWORD"
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
