resource "aws_s3_bucket" "documents" {
  bucket        = var.document_bucket
  force_destroy = var.use_localstack
}

resource "aws_sqs_queue" "processing_dlq" {
  name = var.processing_dlq
}

resource "aws_sqs_queue" "processing" {
  name = var.processing_queue

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_secretsmanager_secret" "application" {
  name                    = "agreement-intelligence/application"
  recovery_window_in_days = var.use_localstack ? 0 : 7
}

output "document_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "processing_queue_url" {
  value = aws_sqs_queue.processing.url
}

output "application_secret_arn" {
  value = aws_secretsmanager_secret.application.arn
}
