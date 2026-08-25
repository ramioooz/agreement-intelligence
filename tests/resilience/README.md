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

The container checks cover worker restart with a durable queued message, controlled backlog drain, and PostgreSQL interruption/recovery. Each script cleans its disposable volumes on exit. Expected results are one durable outcome per idempotency key, no duplicate workflow side effects, a drained queue after worker recovery, a failed database operation during interruption, and successful database-dependent operation after restart.

Provider unavailability must produce bounded retry or an explicit safe unavailable state. Hybrid retrieval remains usable through lexical search; a provider result must never be falsely reported as completed.

These tests measure local recovery only. Managed-service failover, multi-AZ recovery, autoscaling, and AWS disaster recovery remain deferred with the real cloud deployment stories.
