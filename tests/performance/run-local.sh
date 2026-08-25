#!/bin/sh
set -eu

[ "${PERFORMANCE_TEST_CONFIRM:-}" = "synthetic" ] || {
  echo "Set PERFORMANCE_TEST_CONFIRM=synthetic to confirm synthetic-data-only execution." >&2
  exit 1
}
: "${PERFORMANCE_ACCESS_TOKEN:?required}"
: "${PERFORMANCE_ORGANIZATION_ID:?required}"
: "${PERFORMANCE_WORKSPACE_ID:?required}"

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
artifact_dir="$repo_root/artifacts/performance"
network=${PERFORMANCE_COMPOSE_NETWORK:-agreement-intelligence_default}
mkdir -p "$artifact_dir"

for scenario in repository search questions; do
  echo "Running $scenario synthetic performance scenario"
  docker run --rm --network "$network" \
    -v "$repo_root/tests/performance:/performance:ro" \
    -v "$artifact_dir:/artifacts" \
    -e PERFORMANCE_API_BASE_URL="${PERFORMANCE_API_BASE_URL:-http://api:8000}" \
    -e PERFORMANCE_ACCESS_TOKEN \
    -e PERFORMANCE_ORGANIZATION_ID \
    -e PERFORMANCE_WORKSPACE_ID \
    -e PERFORMANCE_AGREEMENT_ID="${PERFORMANCE_AGREEMENT_ID:-}" \
    -e PERFORMANCE_INCLUDE_UPLOAD="${PERFORMANCE_INCLUDE_UPLOAD:-false}" \
    -e PERFORMANCE_VUS="${PERFORMANCE_VUS:-2}" \
    -e PERFORMANCE_ITERATIONS="${PERFORMANCE_ITERATIONS:-10}" \
    -e PERFORMANCE_QUESTION_ITERATIONS="${PERFORMANCE_QUESTION_ITERATIONS:-3}" \
    grafana/k6:2.1.0 run "/performance/k6/$scenario.js" \
      --summary-export "/artifacts/$scenario-summary.json"
done

echo "Performance summaries: $artifact_dir"
