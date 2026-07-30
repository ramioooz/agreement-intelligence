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
grep -Eq '^[[:space:]]+run: git diff --check "origin/\$\{\{ github\.base_ref \}\}\.\.\.HEAD"$' "$workflow"

if grep -Eiq 'test-stack|stack-check|stack-up|trivy|gitleaks|dependency-review|codeql|docker[ -]compose|docker compose|container scan|secret scan' "$workflow"; then
  echo "Workflow includes checks outside the agreed first CI scope"
  exit 1
fi
