# Local performance and recovery baseline

The repeatable commands and objectives are now version controlled. Numeric results are intentionally recorded only after a run against the reviewer’s active synthetic stack because bearer tokens, host load, and optional provider availability materially affect the measurements.

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

## Current limitations

- Local Docker timing is not proof of AWS networking, managed database, load balancer, IAM, or autoscaling behavior.
- Provider latency and cost vary and are reported rather than used as a flaky release gate.
- Sustained soak, multi-region recovery, and real cloud disaster recovery remain deferred with the cloud deployment work.
