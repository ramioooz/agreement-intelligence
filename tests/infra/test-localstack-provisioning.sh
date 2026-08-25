#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
terraform_dir="$repo_root/infra/terraform"
endpoint="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
region="${AWS_REGION:-us-east-1}"
environment_name="ci-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
run_dir="$(mktemp -d "${TMPDIR:-/tmp}/agreement-intelligence-terraform.XXXXXX")"
config_dir="$run_dir/config"

case "$run_dir" in
  "${TMPDIR:-/tmp}"/agreement-intelligence-terraform.*) ;;
  *)
    echo "Refusing to use unexpected temporary directory: $run_dir" >&2
    exit 1
    ;;
esac

for command_name in terraform tflocal aws curl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name is required for LocalStack provisioning verification" >&2
    exit 1
  }
done

curl --fail --silent "$endpoint/_localstack/health" >/dev/null || {
  echo "LocalStack is not healthy at $endpoint" >&2
  exit 1
}

mkdir -p "$config_dir"
cp -R "$terraform_dir/." "$config_dir/"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="$region"
export TF_VAR_region="$region"
export TF_VAR_endpoint="$endpoint"
export TF_VAR_use_localstack=true
export TF_VAR_environment_name="$environment_name"
export TF_UNPROXIED_CMDS="fmt,validate,version,plan,apply,destroy"

cleanup() {
  tflocal -chdir="$config_dir" destroy -auto-approve -input=false >/dev/null 2>&1 || true
  rm -rf "$run_dir"
}
trap cleanup EXIT

terraform -chdir="$config_dir" init -backend=false -input=false >/dev/null
tflocal -chdir="$config_dir" plan -input=false -lock=false -out=tfplan >/dev/null
tflocal -chdir="$config_dir" apply -auto-approve -input=false tfplan >/dev/null

bucket="$(terraform -chdir="$config_dir" output -raw document_bucket)"
aws --endpoint-url "$endpoint" s3api head-bucket --bucket "$bucket" >/dev/null

versioning="$(aws --endpoint-url "$endpoint" s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)"
test "$versioning" = "Enabled"

encryption="$(aws --endpoint-url "$endpoint" s3api get-bucket-encryption --bucket "$bucket" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text)"
test "$encryption" = "AES256"

for output_name in \
  processing_queue_url processing_dlq_url \
  notification_queue_url notification_dlq_url \
  export_queue_url export_dlq_url; do
  queue_url="$(terraform -chdir="$config_dir" output -raw "$output_name")"
  aws --endpoint-url "$endpoint" sqs get-queue-attributes \
    --queue-url "$queue_url" \
    --attribute-names QueueArn SqsManagedSseEnabled \
    >/dev/null
done

for output_name in processing_queue_url notification_queue_url export_queue_url; do
  queue_url="$(terraform -chdir="$config_dir" output -raw "$output_name")"
  redrive="$(aws --endpoint-url "$endpoint" sqs get-queue-attributes --queue-url "$queue_url" --attribute-names RedrivePolicy --query 'Attributes.RedrivePolicy' --output text)"
  test -n "$redrive"
  test "$redrive" != "None"
done

secret_arn="$(terraform -chdir="$config_dir" output -raw application_secret_arn)"
aws --endpoint-url "$endpoint" secretsmanager describe-secret --secret-id "$secret_arn" >/dev/null

tflocal -chdir="$config_dir" destroy -auto-approve -input=false >/dev/null
trap - EXIT
rm -rf "$run_dir"
