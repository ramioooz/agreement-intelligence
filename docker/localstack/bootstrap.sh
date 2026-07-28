#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 apply|verify" >&2
  exit 2
}

test "$#" -eq 1 || usage
action=$1
case "$action" in
  apply | verify) ;;
  *) usage ;;
esac

endpoint=${LOCALSTACK_ENDPOINT:-http://localstack:4566}
export AWS_DEFAULT_REGION=${AWS_REGION:?required}

aws_local() {
  awslocal --endpoint-url "$endpoint" "$@"
}

ensure_bucket() {
  if ! aws_local s3api head-bucket --bucket "$S3_DOCUMENT_BUCKET" \
    >/dev/null 2>&1; then
    if test "$AWS_REGION" = "us-east-1"; then
      aws_local s3api create-bucket \
        --bucket "$S3_DOCUMENT_BUCKET" \
        >/dev/null
    else
      aws_local s3api create-bucket \
        --bucket "$S3_DOCUMENT_BUCKET" \
        --create-bucket-configuration "LocationConstraint=$AWS_REGION" \
        >/dev/null
    fi
  fi

  aws_local s3api put-public-access-block \
    --bucket "$S3_DOCUMENT_BUCKET" \
    --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
    >/dev/null
}

queue_url() {
  aws_local sqs get-queue-url \
    --queue-name "$1" \
    --query QueueUrl \
    --output text
}

ensure_queue() {
  aws_local sqs create-queue --queue-name "$1" >/dev/null
}

remove_unapproved_queues() {
  queue_urls=$(aws_local sqs list-queues --query QueueUrls --output json)
  unapproved_queue_urls=$(python3 - "$queue_urls" \
    "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ" \
    "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ" \
    "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ" <<'PY'
import json
import sys
from urllib.parse import unquote, urlparse

expected = set(sys.argv[2:])
for queue_url in json.loads(sys.argv[1]) or []:
    queue_name = unquote(urlparse(queue_url).path.rstrip("/").rsplit("/", 1)[-1])
    if queue_name not in expected:
        print(queue_url)
PY
)
  printf '%s\n' "$unapproved_queue_urls" \
    | while IFS= read -r unapproved_queue_url; do
      test -n "$unapproved_queue_url" || continue
      aws_local sqs delete-queue \
        --queue-url "$unapproved_queue_url" \
        >/dev/null
    done
}

configure_redrive() {
  primary_name=$1
  dlq_name=$2
  primary_url=$(queue_url "$primary_name")
  dlq_url=$(queue_url "$dlq_name")
  dlq_arn=$(aws_local sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text)
  redrive="{\"deadLetterTargetArn\":\"$dlq_arn\",\"maxReceiveCount\":\"5\"}"
  attributes=$(python3 - "$redrive" <<'PY'
import json
import sys

print(json.dumps({"RedrivePolicy": sys.argv[1]}))
PY
)
  aws_local sqs set-queue-attributes \
    --queue-url "$primary_url" \
    --attributes "$attributes" \
    >/dev/null
}

clear_redrive() {
  dlq_url=$(queue_url "$1")
  aws_local sqs set-queue-attributes \
    --queue-url "$dlq_url" \
    --attributes '{"RedrivePolicy":""}' \
    >/dev/null
}

verify_bucket() {
  aws_local s3api head-bucket --bucket "$S3_DOCUMENT_BUCKET" >/dev/null
  for setting in \
    BlockPublicAcls \
    IgnorePublicAcls \
    BlockPublicPolicy \
    RestrictPublicBuckets; do
    value=$(aws_local s3api get-public-access-block \
      --bucket "$S3_DOCUMENT_BUCKET" \
      --query "PublicAccessBlockConfiguration.$setting" \
      --output text)
    test "$value" = "True"
  done
}

verify_queue_pair() {
  primary_url=$(queue_url "$1")
  dlq_url=$(queue_url "$2")
  dlq_arn=$(aws_local sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text)
  redrive=$(aws_local sqs get-queue-attributes \
    --queue-url "$primary_url" \
    --attribute-names RedrivePolicy \
    --query Attributes.RedrivePolicy \
    --output text)
  python3 - "$redrive" "$dlq_arn" <<'PY'
import json
import sys

policy = json.loads(sys.argv[1])
assert policy == {
    "deadLetterTargetArn": sys.argv[2],
    "maxReceiveCount": "5",
}
PY
}

verify_no_redrive() {
  dlq_url=$(queue_url "$1")
  attributes=$(aws_local sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names RedrivePolicy \
    --output json)
  python3 - "$attributes" <<'PY'
import json
import sys

attributes = json.loads(sys.argv[1] or "{}").get("Attributes", {})
assert "RedrivePolicy" not in attributes, attributes
PY
}

verify_exact_queues() {
  queue_urls=$(aws_local sqs list-queues --query QueueUrls --output json)
  python3 - "$queue_urls" \
    "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ" \
    "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ" \
    "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ" <<'PY'
import json
import sys
from urllib.parse import urlparse

actual = sorted(
    urlparse(queue_url).path.rstrip("/").rsplit("/", 1)[-1]
    for queue_url in json.loads(sys.argv[1])
)
expected = sorted(sys.argv[2:])
assert actual == expected, (actual, expected)
PY
}

apply() {
  ensure_bucket
  for queue in \
    "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ" \
    "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ" \
    "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ"; do
    ensure_queue "$queue"
  done
  remove_unapproved_queues
  clear_redrive "$SQS_PROCESSING_DLQ"
  clear_redrive "$SQS_EXPORT_DLQ"
  clear_redrive "$SQS_NOTIFICATION_DLQ"
  configure_redrive "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ"
  configure_redrive "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ"
  configure_redrive "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ"
}

verify() {
  verify_bucket
  verify_exact_queues
  verify_queue_pair "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ"
  verify_queue_pair "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ"
  verify_queue_pair "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ"
  verify_no_redrive "$SQS_PROCESSING_DLQ"
  verify_no_redrive "$SQS_EXPORT_DLQ"
  verify_no_redrive "$SQS_NOTIFICATION_DLQ"
}

case "$action" in
  apply)
    apply
    verify
    ;;
  verify)
    verify
    ;;
esac
