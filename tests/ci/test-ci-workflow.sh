#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

workflow=".github/workflows/ci.yml"

test -f "$workflow" || {
  echo "Missing CI workflow: $workflow"
  exit 1
}

grep -Eq '^name: CI$' "$workflow"
grep -Eq "^['\"]on['\"]:$" "$workflow"
grep -Eq '^[[:space:]]+pull_request:$' "$workflow"
grep -Eq '^[[:space:]]+branches: \[main\]$' "$workflow"
grep -Eq '^permissions:$' "$workflow"
grep -Eq '^[[:space:]]+contents: read$' "$workflow"
grep -Eq '^[[:space:]]+pull-requests: read$' "$workflow"
grep -Eq '^[[:space:]]+fetch-depth: 0$' "$workflow"
grep -Eq '^[[:space:]]+run: make setup$' "$workflow"
grep -Eq '^[[:space:]]+run: make check$' "$workflow"
grep -Eq '^[[:space:]]+run: pnpm audit --prod --audit-level high$' "$workflow"
grep -Eq '^[[:space:]]+run: uv run pip-audit$' "$workflow"
grep -Eq '^[[:space:]]+uses: gitleaks/gitleaks-action@v3$' "$workflow"
grep -Eq '^[[:space:]]+GITLEAKS_ENABLE_COMMENTS: "false"$' "$workflow"
grep -Eq '^[[:space:]]+run: git diff --check "origin/\$\{\{ github\.base_ref \}\}\.\.\.HEAD"$' "$workflow"

source_checks_line=$(grep -n 'name: Run source checks' "$workflow" | cut -d: -f1)
secret_scan_line=$(grep -n 'name: Scan for leaked secrets' "$workflow" | cut -d: -f1)
test "$source_checks_line" -lt "$secret_scan_line" || {
  echo "Source checks must run before secret scan artifacts are generated."
  exit 1
}

if grep -Eiq 'test-stack|stack-check|stack-up|trivy|dependency-review|codeql|docker[ -]compose|docker compose|container scan|container image scan' "$workflow"; then
  echo "Workflow includes checks outside the agreed lightweight CI security scope"
  exit 1
fi
