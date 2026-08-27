#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

required_files='
LICENSE
SECURITY.md
CODE_OF_CONDUCT.md
CONTRIBUTING.md
docs/README.md
docs/getting-started.md
docs/roadmap.md
docs/architecture/overview.md
docs/operations/platform-foundation.md
docs/security/threat-model.md
docs/security/responsible-ai.md
docs/testing/manual-test-plan.md
docs/testing/test-data.md
docs/testing/evidence-template.md
docs/testing/release-evidence.md
docs/testing/api-testing.md
docs/testing/insomnia/agreement-intelligence.yaml
scripts/check-doc-links.mjs
scripts/release-check.sh
scripts/validate-release-no-key.sh
scripts/manual-qa-state.sh
docs/assets/public-release-demo.webm
'

for path in $required_files; do
  test -s "$path" || {
    echo "Missing required public-release artifact: $path"
    exit 1
  }
done

node scripts/check-doc-links.mjs

fixture_root=$(mktemp -d "${TMPDIR:-/tmp}/agreement-doc-links.XXXXXX")
trap 'rm -rf "$fixture_root"' EXIT HUP INT TERM
printf '# Broken\n\n[Missing](absent.md)\n' >"$fixture_root/README.md"
if node scripts/check-doc-links.mjs "$fixture_root" >/dev/null 2>&1; then
  echo "The documentation checker accepted a broken relative link."
  exit 1
fi

node <<'NODE'
const fs = require("node:fs");

const manualPath = "docs/testing/manual-test-plan.md";
const manual = fs.readFileSync(manualPath, "utf8");
const requiredSections = [
  "Execution conventions",
  "Installation and health",
  "Authentication and authorization",
  "Agreement repository and analysis",
  "Playbooks, search, Q&A, and comparison",
  "Review, approval, audit, and packages",
  "API, MCP, and operations",
  "Browser quality and accessibility",
  "Failure recovery and security",
  "Release traceability matrix",
];
for (const heading of requiredSections) {
  if (!manual.includes(`## ${heading}`)) {
    throw new Error(`${manualPath} is missing section: ${heading}`);
  }
}

const matches = [...manual.matchAll(/^### (MQA-[A-Z]+-\d{3}) — .*$/gm)];
if (matches.length < 35) {
  throw new Error(`Expected at least 35 detailed MQA cases; found ${matches.length}.`);
}
const seen = new Set();
const fields = [
  "**Purpose and risk:**",
  "**Identity:**",
  "**Preconditions and test data:**",
  "**Steps:**",
  "**Expected result:**",
  "**Evidence:**",
  "**Cleanup:**",
  "**Result:**",
];
for (let index = 0; index < matches.length; index += 1) {
  const id = matches[index][1];
  if (seen.has(id)) throw new Error(`Duplicate manual QA ID: ${id}`);
  seen.add(id);
  const start = matches[index].index;
  const end = matches[index + 1]?.index ?? manual.length;
  const block = manual.slice(start, end);
  for (const field of fields) {
    if (!block.includes(field)) throw new Error(`${id} is missing ${field}`);
  }
  if (!/^\d+\. /m.test(block)) throw new Error(`${id} has no numbered steps.`);
}

const collectionPath = "docs/testing/insomnia/agreement-intelligence.yaml";
const collection = fs.readFileSync(collectionPath, "utf8");
for (const placeholder of [
  "base_url",
  "token_url",
  "client_id",
  "username",
  "password",
  "organization_id",
  "workspace_id",
  "agreement_id",
  "review_id",
  "access_token",
]) {
  if (!collection.includes(placeholder)) {
    throw new Error(`${collectionPath} is missing placeholder: ${placeholder}`);
  }
}
for (const forbidden of [
  /Authorization:\s*Bearer\s+[A-Za-z0-9._-]+/i,
  /sk-[A-Za-z0-9_-]{12,}/,
  /change-me/i,
  /Cookie:/i,
  /@[A-Za-z0-9.-]+\.(com|net|org)\b/i,
]) {
  if (forbidden.test(collection)) {
    throw new Error(`${collectionPath} contains a forbidden credential or identity value.`);
  }
}
NODE

make -n release-check >/dev/null
tests/docs/test-release-no-key-mode.sh
tests/docs/test-synthetic-fixtures.sh
grep -q -- '--force-recreate' scripts/release-check.sh
grep -q 'second-tenant-setup' scripts/manual-qa-state.sh
grep -q 'failed-job-setup' scripts/manual-qa-state.sh
grep -q 'PUBLIC_RELEASE_VIDEO_PATH' apps/web/e2e/public-release.spec.ts
pnpm --filter @agreement-intelligence/web exec playwright test --project release --list >/dev/null

echo "Public documentation contracts pass."
