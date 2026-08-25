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

variable "name_prefix" {
  type        = string
  description = "Prefix shared by provisioned resources."
  default     = "agreement-intelligence"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.name_prefix))
    error_message = "name_prefix must contain only lowercase letters, digits, and hyphens."
  }
}

variable "environment_name" {
  type        = string
  description = "Environment suffix used to isolate resource names and state."
  default     = "local"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.environment_name))
    error_message = "environment_name must contain only lowercase letters, digits, and hyphens."
  }
}
