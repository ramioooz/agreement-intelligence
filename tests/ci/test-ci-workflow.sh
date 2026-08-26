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
grep -Eq '^[[:space:]]+run: make ai-eval$' "$workflow"
grep -Eq '^[[:space:]]+if: always\(\)$' "$workflow"
grep -Eq '^[[:space:]]+uses: actions/upload-artifact@[0-9a-f]{40} # v4$' "$workflow"
grep -Eq '^[[:space:]]+name: unified-ai-quality-report$' "$workflow"
grep -Eq '^[[:space:]]+path: artifacts/evaluation/$' "$workflow"
grep -Eq '^[[:space:]]+run: pnpm audit --audit-level high$' "$workflow"
grep -Eq '^[[:space:]]+run: uv run pip-audit --ignore-vuln PYSEC-2026-3046 --ignore-vuln PYSEC-2026-2447$' "$workflow"
grep -Eq '^[[:space:]]+run: make terraform-check$' "$workflow"
grep -Eq '^[[:space:]]+localstack:$' "$workflow"
grep -Eq 'SERVICES: s3,sqs,secretsmanager' "$workflow"
grep -Eq 'name: Install local infrastructure tools' "$workflow"
grep -Eq 'terraform-local==' "$workflow"
grep -Eq 'checkov==' "$workflow"
grep -Eq 'name: Provision and inspect emulated infrastructure' "$workflow"
grep -Eq '^[[:space:]]+run: make terraform-provision-local$' "$workflow"
grep -Eq '^[[:space:]]+uses: gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e # v3$' "$workflow"
grep -Eq '^[[:space:]]+GITLEAKS_ENABLE_COMMENTS: "false"$' "$workflow"
grep -Eq '^[[:space:]]+run: git diff --check "origin/\$\{\{ github\.base_ref \}\}\.\.\.HEAD"$' "$workflow"

if ! awk '
  $1 == "uses:" && index($2, "/") && index($2, "@") {
    split($2, reference, "@")
    sha = reference[length(reference)]
    if (length(sha) != 40 || sha !~ /^[0123456789abcdef]+$/) {
      print "Mutable GitHub Action reference: " $2
      invalid = 1
    }
  }
  END { exit invalid }
' "$workflow"; then
  echo "Every GitHub Action must be pinned to a full commit SHA."
  exit 1
fi

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
