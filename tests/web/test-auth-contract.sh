#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

env_file=$(mktemp)
invalid_env_file=$(mktemp)
cleanup() {
  rm -f "$env_file" "$invalid_env_file"
}
trap cleanup EXIT INT TERM

test -f apps/web/src/auth.ts || {
  echo "Missing Auth.js server configuration"
  exit 1
}

test -f 'apps/web/src/app/api/auth/[...nextauth]/route.ts' || {
  echo "Missing Auth.js route handler"
  exit 1
}

test -f apps/web/src/proxy.ts || {
  echo "Missing protected-route proxy"
  exit 1
}

grep -q 'next-auth' apps/web/package.json
grep -q 'Keycloak' apps/web/src/auth.ts
grep -q 'OIDC_ISSUER' apps/web/src/auth.ts
grep -q 'OIDC_INTERNAL_ISSUER' apps/web/src/auth.ts
grep -q 'httpOnly' apps/web/src/auth.ts
grep -q 'sameSite' apps/web/src/auth.ts
grep -q 'secure:' apps/web/src/auth.ts
grep -q 'maxAge:' apps/web/src/auth.ts
grep -q 'secret:' apps/web/src/auth.ts
grep -q 'export const { handlers, auth, signIn, signOut }' apps/web/src/auth.ts
grep -q 'export { auth as proxy }' apps/web/src/proxy.ts
grep -Fq '"/dashboard/:path*"' apps/web/src/proxy.ts
grep -q 'AUTH_SECRET' .env.example
grep -q 'OIDC_INTERNAL_ISSUER=http://keycloak:8080/realms/agreement-intelligence' .env.example
grep -q 'OIDC_ISSUER=http://localhost:8080/realms/agreement-intelligence' .env.example
grep -q 'WEB_PUBLIC_ORIGIN=http://localhost:3000' .env.example
grep -q 'AUTH_URL=http://localhost:3000' .env.example
grep -q 'AUTH_SECRET:' compose.yaml
grep -q 'WEB_PUBLIC_ORIGIN:' compose.yaml
grep -q 'OIDC_INTERNAL_ISSUER:' compose.yaml
grep -q 'api/auth/callback/keycloak' docker/keycloak/bootstrap.sh
grep -q 'http://localhost:3000/api/auth/callback/keycloak' docker/keycloak/realm/agreement-intelligence-realm.json
grep -q '^AUTH_SECRET$' scripts/validate-stack-env.sh
grep -q '^WEB_PUBLIC_ORIGIN$' scripts/validate-stack-env.sh
grep -q 'WEB_PUBLIC_ORIGIN port must match WEB_PORT' scripts/validate-stack-env.sh

sed 's/change-me/dev-only/g' .env.example >"$env_file"
STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh

for replacement in \
  's/AUTH_SECRET=dev-only-application-session-secret/AUTH_SECRET=change-me-application-session-secret/' \
  's/WEB_PUBLIC_ORIGIN=http:\/\/localhost:3000/WEB_PUBLIC_ORIGIN=http:\/\/localhost:3000\//' \
  's/WEB_PUBLIC_ORIGIN=http:\/\/localhost:3000/WEB_PUBLIC_ORIGIN=http:\/\/localhost:3001/' \
  's/WEB_PUBLIC_ORIGIN=http:\/\/localhost:3000/WEB_PUBLIC_ORIGIN=localhost:3000/'; do
  sed "$replacement" "$env_file" >"$invalid_env_file"
  if STACK_ENV_FILE="$invalid_env_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
    echo "Invalid auth environment unexpectedly passed: $replacement"
    exit 1
  fi
done

if grep -Eriq 'cognito|microsoft|entra|fake agreement|sample agreement|bearer token' apps/web/src; then
  echo "Auth shell includes scope deferred from this PR"
  exit 1
fi
