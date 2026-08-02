variable "region" {
  type        = string
  description = "AWS region used by LocalStack or real AWS."
  default     = "us-east-1"
}

variable "endpoint" {
  type        = string
  description = "AWS-compatible endpoint used for local validation."
  default     = "http://localhost:4566"
}

variable "use_localstack" {
  type        = bool
  description = "Whether to configure the provider for LocalStack."
  default     = true
}

variable "document_bucket" {
  type        = string
  description = "Agreement document bucket name."
  default     = "agreement-intelligence-documents"
}

variable "processing_queue" {
  type        = string
  description = "Durable document processing queue name."
  default     = "agreement-processing"
}

variable "processing_dlq" {
  type        = string
  description = "Durable document processing dead-letter queue name."
  default     = "agreement-processing-dlq"
}
