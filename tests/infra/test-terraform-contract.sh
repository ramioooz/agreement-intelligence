#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
terraform_dir="$repo_root/infra/terraform"

required_files="
$terraform_dir/outputs.tf
$terraform_dir/local.auto.tfvars.example
$terraform_dir/checkov.yaml
$repo_root/tests/infra/test-localstack-provisioning.sh
"

for required_file in $required_files; do
  test -f "$required_file" || {
    echo "Missing Terraform verification file: $required_file" >&2
    exit 1
  }
done

for resource in \
  notification notification_dlq \
  export export_dlq; do
  grep -Eq "resource \"aws_sqs_queue\" \"$resource\"" "$terraform_dir/main.tf" || {
    echo "Missing Terraform queue resource: $resource" >&2
    exit 1
  }
done

grep -Eq 'resource "aws_s3_bucket_versioning" "documents"' "$terraform_dir/main.tf"
grep -Eq 'resource "aws_s3_bucket_server_side_encryption_configuration" "documents"' "$terraform_dir/main.tf"
grep -Eq 'resource "aws_s3_bucket_public_access_block" "documents"' "$terraform_dir/main.tf"
grep -Eq 'resource "aws_secretsmanager_secret" "application"' "$terraform_dir/main.tf"
grep -Eq 'default[[:space:]]*=[[:space:]]*true' "$terraform_dir/variables.tf"
grep -Eq 'SERVICES: s3,sqs,secretsmanager' "$repo_root/compose.yaml"

command -v terraform >/dev/null 2>&1 || {
  echo "terraform is required for this contract" >&2
  exit 1
}

terraform -chdir="$terraform_dir" fmt -check
terraform -chdir="$terraform_dir" init -backend=false -input=false >/dev/null
terraform -chdir="$terraform_dir" validate

command -v tflocal >/dev/null 2>&1 || {
  echo "tflocal is required; LocalStack validation cannot be skipped" >&2
  exit 1
}

# The checked-in provider endpoints are authoritative. Prevent terraform-local
# from generating unsupported overrides for every AWS service.
export TF_UNPROXIED_CMDS="fmt,validate,version,plan,apply,destroy"
tflocal -chdir="$terraform_dir" plan -input=false -lock=false >/dev/null

command -v checkov >/dev/null 2>&1 || {
  echo "checkov is required; Terraform policy checks cannot be skipped" >&2
  exit 1
}

checkov --config-file "$terraform_dir/checkov.yaml" --directory "$terraform_dir"
