provider "aws" {
  region                      = var.region
  access_key                  = var.use_localstack ? "test" : null
  secret_key                  = var.use_localstack ? "test" : null
  skip_credentials_validation = var.use_localstack
  skip_metadata_api_check     = var.use_localstack
  skip_requesting_account_id  = var.use_localstack
  s3_use_path_style           = var.use_localstack

  dynamic "endpoints" {
    for_each = var.use_localstack ? [var.endpoint] : []
    content {
      s3             = endpoints.value
      sqs            = endpoints.value
      secretsmanager = endpoints.value
    }
  }
}
