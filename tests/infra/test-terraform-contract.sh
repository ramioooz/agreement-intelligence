#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
terraform_dir="$repo_root/infra/terraform"

command -v terraform >/dev/null 2>&1 || {
  echo "terraform is required for this contract" >&2
  exit 1
}

terraform -chdir="$terraform_dir" fmt -check
terraform -chdir="$terraform_dir" init -backend=false -input=false >/dev/null
terraform -chdir="$terraform_dir" validate

if command -v tflocal >/dev/null 2>&1; then
  tflocal -chdir="$terraform_dir" plan -input=false -lock=false >/dev/null
else
  echo "tflocal not installed; skipped LocalStack plan" >&2
fi
