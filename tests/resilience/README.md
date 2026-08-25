# Isolated local recovery checks

These opt-in checks create disposable Compose projects with unique names, ports, networks, and volumes. They never stop or delete the normal `agreement-intelligence` project or its data.

Run focused in-process contracts:

```bash
uv run python tests/resilience/test-duplicate-delivery.py
uv run python tests/resilience/test-provider-timeout.py
```

Run the complete isolated recovery set:

```bash
RESILIENCE_TEST_CONFIRM=isolated make resilience-local
```

The container checks cover worker restart with a durable queued message,
controlled backlog drain, and PostgreSQL interruption/recovery. The worker checks
create real processing records, immutable source objects, and completed processing
artifacts. The database check queries the actual API readiness endpoint before,
during, and after the interruption. Each script cleans its disposable volumes on
exit and never touches normal developer volumes or data.

The worker-restart scenario enforces the local idle objective that a real queued
job reaches `processing_started_at` within five seconds. Backlog timing is reported
separately because a cold worker restart and queued work intentionally exercise
recovery rather than steady-state latency.

Provider unavailability must produce bounded retry or an explicit safe unavailable state. Hybrid retrieval remains usable through lexical search; a provider result must never be falsely reported as completed.

These tests measure local recovery only. Managed-service failover, multi-AZ recovery, autoscaling, and AWS disaster recovery remain deferred with the real cloud deployment stories.
