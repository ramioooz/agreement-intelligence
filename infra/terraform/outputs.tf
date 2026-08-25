output "document_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "processing_queue_url" {
  value = aws_sqs_queue.processing.url
}

output "processing_dlq_url" {
  value = aws_sqs_queue.processing_dlq.url
}

output "notification_queue_url" {
  value = aws_sqs_queue.notification.url
}

output "notification_dlq_url" {
  value = aws_sqs_queue.notification_dlq.url
}

output "export_queue_url" {
  value = aws_sqs_queue.export.url
}

output "export_dlq_url" {
  value = aws_sqs_queue.export_dlq.url
}

output "application_secret_arn" {
  value = aws_secretsmanager_secret.application.arn
}
