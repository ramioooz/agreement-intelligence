# Local incident runbooks

Use these runbooks for the containerized local environment. Begin with read-only
diagnostics, preserve audit evidence, and avoid printing secrets or document content.

| Incident | Runbook |
| --- | --- |
| Processing remains queued or processing | [Stuck processing](stuck-processing.md) |
| Hosted model or embedding provider is unavailable | [Provider outage](provider-outage.md) |
| SQS depth or processing delay increases | [Queue backlog](queue-backlog.md) |
| A promoted model/configuration causes regressions | [Bad model release](bad-model-release.md) |
| A credential may be exposed | [Compromised credential](compromised-credential.md) |
| A user can see another tenant's data | [Tenant access incident](tenant-access-incident.md) |

For data recovery, use [Local backup and restore](../backup-restore.md). Real AWS
incident response and disaster recovery remain unvalidated.

