locals {
  resource_prefix         = "${var.name_prefix}-${var.environment_name}"
  document_bucket_name    = "${local.resource_prefix}-documents"
  processing_queue_name   = "${local.resource_prefix}-agreement-processing"
  processing_dlq_name     = "${local.processing_queue_name}-dlq"
  notification_queue_name = "${local.resource_prefix}-notifications"
  notification_dlq_name   = "${local.notification_queue_name}-dlq"
  export_queue_name       = "${local.resource_prefix}-exports"
  export_dlq_name         = "${local.export_queue_name}-dlq"
  application_secret_name = "${var.name_prefix}/${var.environment_name}/application"
}

resource "aws_s3_bucket" "documents" {
  bucket        = local.document_bucket_name
  force_destroy = var.use_localstack

  lifecycle {
    precondition {
      condition     = length(local.document_bucket_name) >= 3 && length(local.document_bucket_name) <= 63
      error_message = "Composed S3 bucket names must contain between 3 and 63 characters."
    }
  }
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
  name                    = local.processing_dlq_name
  sqs_managed_sse_enabled = true

  lifecycle {
    precondition {
      condition     = length(local.processing_dlq_name) <= 80
      error_message = "Composed SQS queue names must not exceed 80 characters."
    }
  }
}

resource "aws_sqs_queue" "processing" {
  name                    = local.processing_queue_name
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = 5
  })

  lifecycle {
    precondition {
      condition     = length(local.processing_queue_name) <= 80
      error_message = "Composed SQS queue names must not exceed 80 characters."
    }
  }
}

resource "aws_sqs_queue" "notification_dlq" {
  name                    = local.notification_dlq_name
  sqs_managed_sse_enabled = true

  lifecycle {
    precondition {
      condition     = length(local.notification_dlq_name) <= 80
      error_message = "Composed SQS queue names must not exceed 80 characters."
    }
  }
}

resource "aws_sqs_queue" "notification" {
  name                    = local.notification_queue_name
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notification_dlq.arn
    maxReceiveCount     = 5
  })

  lifecycle {
    precondition {
      condition     = length(local.notification_queue_name) <= 80
      error_message = "Composed SQS queue names must not exceed 80 characters."
    }
  }
}

resource "aws_sqs_queue" "export_dlq" {
  name                    = local.export_dlq_name
  sqs_managed_sse_enabled = true

  lifecycle {
    precondition {
      condition     = length(local.export_dlq_name) <= 80
      error_message = "Composed SQS queue names must not exceed 80 characters."
    }
  }
}

resource "aws_sqs_queue" "export" {
  name                    = local.export_queue_name
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.export_dlq.arn
    maxReceiveCount     = 5
  })

  lifecycle {
    precondition {
      condition     = length(local.export_queue_name) <= 80
      error_message = "Composed SQS queue names must not exceed 80 characters."
    }
  }
}

resource "aws_secretsmanager_secret" "application" {
  name                    = local.application_secret_name
  recovery_window_in_days = var.use_localstack ? 0 : 7

  lifecycle {
    precondition {
      condition     = length(local.application_secret_name) >= 1 && length(local.application_secret_name) <= 512
      error_message = "Composed Secrets Manager names must contain between 1 and 512 characters."
    }
  }
}
