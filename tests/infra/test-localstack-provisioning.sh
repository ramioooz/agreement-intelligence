#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
terraform_dir="$repo_root/infra/terraform"
endpoint="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
region="${LOCALSTACK_REGION:-us-east-1}"
environment_name="ci-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"

if [[ ! "$endpoint" =~ ^http://(localhost|127\.0\.0\.1):([0-9]{1,5})$ ]] ||
  ((10#${BASH_REMATCH[2]:-0} < 1 || 10#${BASH_REMATCH[2]:-0} > 65535)); then
  echo "Refusing non-loopback LocalStack endpoint: $endpoint" >&2
  exit 1
fi

for command_name in terraform tflocal aws curl env git python3; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name is required for LocalStack provisioning verification" >&2
    exit 1
  }
done

curl --fail --silent "$endpoint/_localstack/health" >/dev/null || {
  echo "LocalStack is not healthy at $endpoint" >&2
  exit 1
}

terraform_files=(
  .terraform.lock.hcl
  main.tf
  outputs.tf
  providers.tf
  variables.tf
  versions.tf
)
for terraform_file in "${terraform_files[@]}"; do
  tracked_path="infra/terraform/$terraform_file"
  git -C "$repo_root" ls-files --error-unmatch "$tracked_path" >/dev/null || {
    echo "Refusing untracked Terraform input: $tracked_path" >&2
    exit 1
  }
done

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
export TF_UNPROXIED_CMDS="fmt,validate,version,plan,apply,destroy"

localstack_tf_args=(
  "-var=use_localstack=true"
  "-var=endpoint=$endpoint"
  "-var=region=$region"
  "-var=environment_name=$environment_name"
  "-var=name_prefix=agreement-intelligence"
)

run_dir="$(mktemp -d "${TMPDIR:-/tmp}/agreement-intelligence-terraform.XXXXXX")"
config_dir="$run_dir/config"

case "$run_dir" in
  "${TMPDIR:-/tmp}"/agreement-intelligence-terraform.*) ;;
  *)
    echo "Refusing to use unexpected temporary directory: $run_dir" >&2
    exit 1
    ;;
esac

cleanup() {
  if test -d "$config_dir/.terraform"; then
    tflocal -chdir="$config_dir" destroy \
      -auto-approve \
      -input=false \
      "${localstack_tf_args[@]}" \
      >/dev/null 2>&1 || true
  fi
  rm -rf "$run_dir"
}
trap cleanup EXIT

mkdir -p "$config_dir"
for terraform_file in "${terraform_files[@]}"; do
  tracked_path="infra/terraform/$terraform_file"
  cp "$repo_root/$tracked_path" "$config_dir/$terraform_file"
done

terraform -chdir="$config_dir" init -backend=false -input=false >/dev/null
tflocal -chdir="$config_dir" plan \
  -input=false \
  -lock=false \
  "${localstack_tf_args[@]}" \
  >/dev/null
tflocal -chdir="$config_dir" apply \
  -auto-approve \
  -input=false \
  "${localstack_tf_args[@]}" \
  >/dev/null

bucket="$(terraform -chdir="$config_dir" output -raw document_bucket)"
aws --endpoint-url "$endpoint" s3api head-bucket --bucket "$bucket" >/dev/null

versioning="$(aws --endpoint-url "$endpoint" s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)"
test "$versioning" = "Enabled"

encryption="$(aws --endpoint-url "$endpoint" s3api get-bucket-encryption --bucket "$bucket" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text)"
test "$encryption" = "AES256"

public_access="$(aws --endpoint-url "$endpoint" s3api get-public-access-block \
  --bucket "$bucket" \
  --query PublicAccessBlockConfiguration \
  --output json)"
python3 -c '
import json
import sys

actual = json.loads(sys.argv[1])
expected = {
    "BlockPublicAcls": True,
    "BlockPublicPolicy": True,
    "IgnorePublicAcls": True,
    "RestrictPublicBuckets": True,
}
assert actual == expected, f"unexpected S3 public access block: {actual!r}"
' "$public_access"

verify_queue_pair() {
  queue_output="$1"
  dlq_output="$2"
  queue_url="$(terraform -chdir="$config_dir" output -raw "$queue_output")"
  dlq_url="$(terraform -chdir="$config_dir" output -raw "$dlq_output")"
  queue_attributes="$(aws --endpoint-url "$endpoint" sqs get-queue-attributes \
    --queue-url "$queue_url" \
    --attribute-names QueueArn SqsManagedSseEnabled RedrivePolicy \
    --query Attributes \
    --output json)"
  dlq_attributes="$(aws --endpoint-url "$endpoint" sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn SqsManagedSseEnabled RedrivePolicy \
    --query Attributes \
    --output json)"

  python3 -c '
import json
import sys

queue = json.loads(sys.argv[1])
dlq = json.loads(sys.argv[2])
assert queue.get("SqsManagedSseEnabled", "").lower() == "true", queue
assert dlq.get("SqsManagedSseEnabled", "").lower() == "true", dlq
assert "RedrivePolicy" not in dlq, dlq
policy = json.loads(queue.get("RedrivePolicy", "{}"))
assert set(policy) == {"deadLetterTargetArn", "maxReceiveCount"}, policy
assert policy["deadLetterTargetArn"] == dlq["QueueArn"], (policy, dlq)
assert int(policy["maxReceiveCount"]) == 5, policy
' "$queue_attributes" "$dlq_attributes"
}

verify_queue_pair processing_queue_url processing_dlq_url
verify_queue_pair notification_queue_url notification_dlq_url
verify_queue_pair export_queue_url export_dlq_url

secret_arn="$(terraform -chdir="$config_dir" output -raw application_secret_arn)"
aws --endpoint-url "$endpoint" secretsmanager describe-secret --secret-id "$secret_arn" >/dev/null

tflocal -chdir="$config_dir" destroy \
  -auto-approve \
  -input=false \
  "${localstack_tf_args[@]}" \
  >/dev/null
trap - EXIT
rm -rf "$run_dir"
