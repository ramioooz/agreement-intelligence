#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

api_id=
web_id=
worker_id=
secret_probe=local-build-context-secret.pem

cleanup() {
  rm -f "$secret_probe"
  for container_id in "$web_id" "$worker_id" "$api_id"; do
    if test -n "$container_id"; then
      docker rm --force "$container_id" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT INT TERM

printf '%s\n' 'test-only-secret-probe' >"$secret_probe"
docker build --file - --tag agreement-intelligence-context-probe:test . <<EOF
FROM node:22.23.1-bookworm-slim
COPY . /context
RUN test ! -e /context/$secret_probe \
    && test ! -e /context/apps/web/.next \
    && test ! -e /context/apps/web/node_modules \
    && test ! -e /context/.venv \
    && test ! -e /context/dist
EOF

for service in web api worker; do
  dockerfile="apps/$service/Dockerfile"
  test -f "$dockerfile" || {
    echo "Missing $dockerfile"
    exit 1
  }

  image="agreement-intelligence-$service:test"
  docker build \
    --file "$dockerfile" \
    --tag "$image" \
    .

  uid=$(docker run --rm --entrypoint sh "$image" -c 'id -u')
  test "$uid" -ne 0 || {
    echo "$service image runs as root"
    exit 1
  }

  health_test=$(docker image inspect \
    --format '{{if .Config.Healthcheck}}{{json .Config.Healthcheck.Test}}{{end}}' \
    "$image")
  test -n "$health_test" || {
    echo "$service image has no health check"
    exit 1
  }
done

api_id=$(docker run --detach --publish 127.0.0.1::8000 \
  agreement-intelligence-api:test)
worker_id=$(docker run --detach agreement-intelligence-worker:test)
web_id=$(docker run --detach \
  --env API_BASE_URL=http://127.0.0.1:9 \
  --publish 127.0.0.1::3000 \
  agreement-intelligence-web:test)

wait_until_healthy() {
  service=$1
  container_id=$2
  attempt=0

  while test "$(docker inspect \
    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
    "$container_id")" != healthy; do
    attempt=$((attempt + 1))
    test "$attempt" -lt 30 || {
      echo "$service did not become healthy"
      docker inspect --format '{{json .State}}' "$container_id"
      docker logs "$container_id"
      exit 1
    }
    sleep 1
  done
}

wait_until_healthy api "$api_id"
wait_until_healthy worker "$worker_id"
wait_until_healthy web "$web_id"

api_port=$(docker port "$api_id" 8000/tcp | awk -F: 'NR == 1 {print $NF}')
web_port=$(docker port "$web_id" 3000/tcp | awk -F: 'NR == 1 {print $NF}')

curl --fail --silent "http://127.0.0.1:$api_port/health/live" \
  | grep -q '"status":"ok"'
curl --fail --silent "http://127.0.0.1:$web_port/" \
  | grep -q 'Agreement Intelligence'

docker logs "$worker_id" 2>&1 | grep -q '"event":"worker.started"'
docker stop --time 10 "$worker_id" >/dev/null
docker logs "$worker_id" 2>&1 | grep -q '"event":"worker.stopped"'
