# Stuck processing

## Trigger and impact

An agreement remains `queued` or `processing`, no new timeline event appears, or the
worker repeatedly handles the same job. Search and deterministic document viewing may
remain available, but fresh analysis and embeddings are delayed.

## Safe diagnostics

```bash
make stack-status
docker compose --project-name agreement-intelligence --env-file .env logs \
  --since 15m worker api localstack
docker compose --project-name agreement-intelligence --env-file .env run --rm \
  --no-deps --entrypoint sh localstack-bootstrap -c \
  'awslocal sqs get-queue-attributes --queue-url "$SQS_PROCESSING_QUEUE" \
   --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible'
```

Use identifiers and safe reason codes from logs; do not copy document text or provider
payloads. Check the agreement processing timeline in the browser.

## Containment and recovery

1. If the worker is unhealthy, restart only it:
   `docker compose --project-name agreement-intelligence --env-file .env restart worker`.
2. Confirm PostgreSQL, LocalStack, and the provider are reachable before requeueing.
3. Use **Requeue analysis** on the agreement page only after the underlying condition
   is corrected. The job contract is idempotent; do not repeatedly click it.
4. If source storage is unavailable, restore it before requeueing.

## Verification and evidence

Run `make stack-check`; verify the agreement reaches `completed` or a controlled
`failed` state and that exactly one current artifact is shown. Record correlation/job
IDs, safe failure reason, queue depth before/after, recovery action, and timestamps.

## Escalation and residual risk

Escalate if retries continue, queue depth grows, or a completed artifact is duplicated.
Historical jobs that failed while the provider was unavailable may require manual
requeue; automatic historical reconciliation is not guaranteed.
