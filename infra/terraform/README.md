# Local AWS-compatible infrastructure

This module provisions the AWS-compatible resources used by local document and
workflow processing: a protected S3 bucket, processing/notification/export SQS
queues and dead-letter queues, and a Secrets Manager-compatible secret.
Resource names include an environment suffix. The provider points to LocalStack
only when `use_localstack=true`.

## LocalStack verification

```bash
uv tool install terraform-local==0.24.1
uv tool install checkov==3.2.495
make terraform-check
make terraform-provision-local
```

`make terraform-check` fails if Terraform, `tflocal`, Checkov, or a required
policy check is unavailable; no verification step is silently skipped.
The checked-in Checkov configuration intentionally excludes eight checks:
bucket access logging, cross-region replication, customer-managed KMS keys,
bucket lifecycle and event notifications, and Secrets Manager rotation. These
controls require the deferred real-AWS logging, key, lifecycle, and rotation
design. Checkov reports configured exclusions separately from its skipped-check
counter, so `Skipped checks: 0` does not mean that no policies are excluded.
`make terraform-provision-local` requires the normal LocalStack service to be
healthy, creates isolated emulated resources, inspects their protection and
redrive settings through the AWS CLI, and destroys them on completion. It stages
only an explicit allowlist of checked-in Terraform files, replaces ambient AWS
credential and profile configuration with non-secret LocalStack values, and
forces the loopback endpoint and `use_localstack=true` on every mutating command.
Copy `local.auto.tfvars.example` only for local experimentation; do not commit
state or credentials.

The LocalStack endpoint defaults to `http://localhost:4566`. Test credentials
are intentionally non-secret and cannot authorize a real AWS account. LocalStack
validates resource wiring, Terraform behavior, and AWS-compatible API calls. It
does **not** prove real IAM enforcement, VPC and network behavior, ECS/RDS/ALB
operation, WAF behavior, Cognito or external identity federation, regional
failure behavior, service quotas, or production performance.

The checked-in Terraform provider block is the source of truth for LocalStack
service endpoints. Verification disables terraform-local's generated
all-service override so it cannot introduce endpoints unsupported by the pinned
AWS provider.

## Migration to AWS

1. Create the approved AWS account and environment and configure encrypted,
   locked remote Terraform state with a separate state key per environment.
2. Set `TF_VAR_use_localstack=false`, choose the approved region and environment
   name, and remove every LocalStack endpoint override and test credential.
3. Run `terraform plan`, retain the plan artifact, and review policy/security
   output and the complete resource diff.
4. Only the repository owner executes the reviewed `terraform apply`.
5. Run a short-lived staging smoke test against real AWS service endpoints.
6. Destroy temporary non-production resources after verification when desired;
   production deletion follows the separate owner-controlled runbook.

Real VPC, ECS, RDS, ALB, WAF, IAM, networking, and identity-federation resources
and validation remain deferred to [#203](https://github.com/ramioooz/agreement-intelligence/issues/203)
under [#200](https://github.com/ramioooz/agreement-intelligence/issues/200).
Never treat a successful LocalStack run as a production deployment approval.
