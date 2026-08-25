# Local performance and recovery baseline

Accepted on 2026-08-25 against a fresh, isolated Docker Compose stack on an
Apple Silicon macOS development host. All records, queues, buckets, networks,
and PostgreSQL volumes used unique disposable names; normal development data was
not read or modified.

## Accepted results

| Objective | Local result | Limit | Outcome |
| --- | ---: | ---: | --- |
| Repository read p95 | 14.761 ms | 500 ms | Pass |
| Filtered search p95 | 26.269 ms | 1,000 ms | Pass |
| Workflow-decision acknowledgement p95 | 48.027 ms | 1,000 ms | Pass |
| Idle queue to processing start | 1.892 s | 5 s | Pass |
| API readiness recovery after PostgreSQL restart | 1 s | 30 s | Pass |
| 20-job backlog drain | 26 s | Reported baseline | Pass |

The backlog produced 20 completed processing jobs, 20 persisted processing
artifacts, and 20 corresponding immutable objects, with no messages remaining.
Its maximum queue-to-start delay was 32.936 seconds while draining the intentionally
accumulated cold backlog; the five-second objective applies to the separate idle
queue scenario above.

Repository and search used 2 virtual users and 10 iterations. The workflow
decision scenario used 1 virtual user and 10 iterations, reused one idempotency
key, and passed every authorization and response-shape check. It ran with
`PERFORMANCE_SKIP_QUESTIONS=true` so the accepted acknowledgement result is not
mixed with optional model-provider latency.

## Commands

```bash
PERFORMANCE_TEST_CONFIRM=synthetic make performance-local
RESILIENCE_TEST_CONFIRM=isolated make resilience-local
```

## Evidence to retain

- k6 JSON summaries from `artifacts/performance/`
- queue backlog size, drain duration, and worker recovery duration
- API recovery duration following a disposable PostgreSQL interruption
- provider-unavailable result showing safe degradation and lexical availability

The worker restart and backlog scenarios create real tenant-scoped processing
records, upload real DOCX sources, publish real SQS messages, and require both
database artifact rows and S3 objects before passing. The database interruption
scenario starts the actual API, observes `/health/ready` return 503 while its
PostgreSQL dependency is stopped, and then observes recovery to 200.

## Current limitations

- Local Docker timing is not proof of AWS networking, managed database, load balancer, IAM, or autoscaling behavior.
- Provider latency and cost vary and are reported rather than used as a flaky release gate.
- Sustained soak, multi-region recovery, and real cloud disaster recovery remain deferred with the cloud deployment work.
- Provider recovery does not automatically backfill historical embeddings or
  indexes. That historical backfill limitation is deferred and tracked by #195.
