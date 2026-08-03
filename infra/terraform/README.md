# Local AWS-compatible infrastructure

This module provisions only the resources needed by the local processing flow:
an S3 document bucket, the processing SQS queue and dead-letter queue, and a
Secrets Manager-compatible secret. By default the AWS provider is pointed at
LocalStack. This is a parity check for resource wiring, not proof of production
AWS networking, IAM, ECS, RDS, ALB, WAF, or federation behavior.

## LocalStack verification

```bash
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform validate
tflocal -chdir=infra/terraform plan
tflocal -chdir=infra/terraform apply -auto-approve
```

The LocalStack endpoint is configurable with `TF_VAR_endpoint` and defaults to
`http://localhost:4566`. No credentials or state files are committed.

## Migration to AWS

1. Configure a reviewed AWS account, region, credentials, and remote state.
2. Set `TF_VAR_use_localstack=false` and provide the approved bucket/queue names.
3. Run `terraform plan` and inspect the complete diff.
4. The repository owner executes `terraform apply` after approval.
5. Run a short-lived staging smoke test, then destroy non-production resources
   when appropriate.

Use a separate backend and state workspace for every real environment. Never
point a production plan at the local endpoint.
