locals {
  resource_prefix = "${var.name_prefix}-${var.environment_name}"
}

resource "aws_s3_bucket" "documents" {
  bucket        = "${local.resource_prefix}-documents"
  force_destroy = var.use_localstack
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_sqs_queue" "processing_dlq" {
  name                    = "${local.resource_prefix}-agreement-processing-dlq"
  sqs_managed_sse_enabled = true
}

resource "aws_sqs_queue" "processing" {
  name                    = "${local.resource_prefix}-agreement-processing"
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "notification_dlq" {
  name                    = "${local.resource_prefix}-notifications-dlq"
  sqs_managed_sse_enabled = true
}

resource "aws_sqs_queue" "notification" {
  name                    = "${local.resource_prefix}-notifications"
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notification_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "export_dlq" {
  name                    = "${local.resource_prefix}-exports-dlq"
  sqs_managed_sse_enabled = true
}

resource "aws_sqs_queue" "export" {
  name                    = "${local.resource_prefix}-exports"
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.export_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_secretsmanager_secret" "application" {
  name                    = "${var.name_prefix}/${var.environment_name}/application"
  recovery_window_in_days = var.use_localstack ? 0 : 7
}
