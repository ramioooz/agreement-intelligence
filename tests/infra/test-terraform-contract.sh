#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
terraform_dir="$repo_root/infra/terraform"
endpoint="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
region="${LOCALSTACK_REGION:-us-east-1}"

if [[ ! "$endpoint" =~ ^http://(localhost|127\.0\.0\.1):([0-9]{1,5})$ ]] ||
  ((10#${BASH_REMATCH[2]:-0} < 1 || 10#${BASH_REMATCH[2]:-0} > 65535)); then
  echo "Refusing non-loopback LocalStack endpoint: $endpoint" >&2
  exit 1
fi

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

while IFS='=' read -r variable_name _; do
  case "$variable_name" in
    AWS_* | TF_VAR_* | TF_CLI_ARGS* | TF_DATA_DIR | TF_CLI_CONFIG_FILE | TF_WORKSPACE)
      unset "$variable_name"
      ;;
  esac
done < <(env)

export AWS_ACCESS_KEY_ID="test"
export AWS_SECRET_ACCESS_KEY="test"
export AWS_CONFIG_FILE="/dev/null"
export AWS_SHARED_CREDENTIALS_FILE="/dev/null"
export AWS_EC2_METADATA_DISABLED="true"
export AWS_REGION="$region"
export AWS_DEFAULT_REGION="$region"

# The checked-in provider endpoints are authoritative. Prevent terraform-local
# from generating unsupported overrides for every AWS service.
export TF_UNPROXIED_CMDS="fmt,validate,version,plan,apply,destroy"
localstack_tf_args=(
  "-var=use_localstack=true"
  "-var=endpoint=$endpoint"
  "-var=region=$region"
  "-var=environment_name=contract"
  "-var=name_prefix=agreement-intelligence"
)
tflocal -chdir="$terraform_dir" plan \
  -input=false \
  -lock=false \
  "${localstack_tf_args[@]}" \
  >/dev/null

assert_plan_rejects_name() {
  expected_message="$1"
  shift

  if plan_output="$(terraform -chdir="$terraform_dir" plan \
    -input=false \
    -lock=false \
    -no-color \
    -var=use_localstack=true \
    "-var=endpoint=$endpoint" \
    "-var=region=$region" \
    "$@" 2>&1)"; then
    echo "Terraform accepted an invalid composed AWS resource name: $*" >&2
    exit 1
  fi

  printf '%s\n' "$plan_output" | grep -Fq "$expected_message" || {
    echo "Terraform rejected the name without the module boundary: $expected_message" >&2
    exit 1
  }
}

assert_plan_rejects_name \
  "name_prefix must start and end with a lowercase letter or digit" \
  -var=name_prefix=-invalid
assert_plan_rejects_name \
  "environment_name must start and end with a lowercase letter or digit" \
  -var=environment_name=invalid-
assert_plan_rejects_name \
  "Composed S3 bucket names must contain between 3 and 63 characters" \
  -var=name_prefix=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

command -v checkov >/dev/null 2>&1 || {
  echo "checkov is required; Terraform policy checks cannot be skipped" >&2
  exit 1
}

configured_checkov_exclusions="$(grep -Ec '^[[:space:]]+- CKV' "$terraform_dir/checkov.yaml")"
echo "Checkov configured exclusions: $configured_checkov_exclusions (documented in infra/terraform/checkov.yaml)"
checkov --config-file "$terraform_dir/checkov.yaml" --directory "$terraform_dir"
