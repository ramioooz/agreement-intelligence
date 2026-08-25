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
| One fresh workflow-decision acknowledgement | <= 71.035 ms | 1,000 ms | Pass |
| Idle queue to processing start after worker restart | 4.568 s | 5 s | Pass |
| API readiness recovery after PostgreSQL restart | 1 s | 30 s | Pass |
| 20-job backlog drain | 22 s | 20 jobs within 120 s | Pass |

The backlog produced 20 completed processing jobs, 20 persisted processing
artifacts, and 20 corresponding immutable objects, with no messages remaining.
Its maximum queue-to-start delay was 28.656 seconds while draining the intentionally
accumulated cold backlog. Observed throughput was 0.909 jobs per second; the
five-second objective applies to the separate idle queue scenario above.

Repository and search used 2 virtual users and 10 iterations. An earlier workflow
run contained one fresh decision followed by idempotent replay reads. Because the
exported summary did not retain per-iteration samples, only its 71.035 ms maximum
is retained as a conservative upper bound for that one fresh acknowledgement; no
workflow p95 is claimed from replay traffic. The corrected harness now permits
exactly one workflow iteration per disposable review and uses a maximum-latency
gate. Additional samples require additional fresh reviews. The run used
`PERFORMANCE_SKIP_QUESTIONS=true`, so provider-dependent Q&A latency is excluded.

## Capacity and bottleneck observation

The tested local recovery envelope is one cold worker draining 20 queued document
jobs within 120 seconds. It completed in 22 seconds. This is a validation envelope,
not a saturation ceiling or production capacity claim. The observed bottleneck is
the single worker's sequential message processing: later jobs waited as long as
28.656 seconds to start even though every job completed and persisted one database
artifact and one S3 object. Multiple worker replicas, autoscaling, and an actual
saturation test remain outside this local-readiness story.

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
- duplicate processing and workflow messages with unchanged PostgreSQL assignment,
  notification, checkpoint, artifact, and final-package counts
- provider-unavailable processing job persisted as `failed` after three attempts
  with `transient_exhausted` and no analysis artifact

The worker restart and backlog scenarios create real tenant-scoped processing
records, upload real DOCX sources, publish real SQS messages, and require both
database artifact rows and S3 objects before passing. The database interruption
scenario starts the actual API, observes `/health/ready` return 503 while its
PostgreSQL dependency is stopped, and then observes recovery to 200.

The restart scenario publishes duplicate processing and workflow messages. It
requires exactly one processing artifact, one review assignment, one notification,
one immutable final package, unchanged LangGraph checkpoint count on redelivery,
and final-package S3 bytes whose SHA-256 values match PostgreSQL. It then runs an
unreachable configured provider through the real worker retry loop and requires a
durable three-attempt `transient_exhausted` failure with no analysis artifact.

## Current limitations

- Local Docker timing is not proof of AWS networking, managed database, load balancer, IAM, or autoscaling behavior.
- Provider latency and cost vary and are reported rather than used as a flaky release gate.
- The 20-job recovery envelope does not establish maximum local throughput or a
  saturation point.
- Sustained soak, multi-region recovery, and real cloud disaster recovery remain deferred with the cloud deployment work.
- Provider recovery does not automatically backfill historical embeddings or
  indexes. That historical backfill limitation is deferred and tracked by #195.
