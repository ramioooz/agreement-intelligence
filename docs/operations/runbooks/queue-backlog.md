# Queue backlog

## Trigger and impact

Visible SQS messages or oldest-message delay rises while completion throughput falls.
Uploads remain accepted, but analysis, indexing, comparison, or workflow transitions
take longer.

## Safe diagnostics

```bash
make stack-status
docker compose --project-name agreement-intelligence --env-file .env run --rm \
  --no-deps --entrypoint sh localstack-bootstrap -c \
  'awslocal sqs get-queue-attributes --queue-url "$SQS_PROCESSING_QUEUE" \
   --attribute-names All'
docker compose --project-name agreement-intelligence --env-file .env logs \
  --since 15m worker
```

Look for retry categories, provider latency, database/storage availability, and worker
health. Do not dump message bodies because they may contain scoped identifiers.

## Containment and recovery

1. Correct the shared dependency failure before increasing consumers.
2. Restart an unhealthy worker and verify it resumes existing messages.
3. Keep SQS as the durable job queue; do not move jobs into Redis.
4. Let normal visibility-timeout/redelivery behavior recover messages. Do not purge the
   queue unless loss of all queued work is explicitly accepted.
5. If the API committed work while SQS publication failed, invoke one authorized
   retry/requeue or new same-scope processing action after recovery. This triggers the
   dispatcher to revisit pending outbox rows; a restart alone does not.

## Verification and evidence

Verify queue depth falls, completed artifacts increase, no duplicate current artifacts
appear, and `make stack-check` passes. Record depth, oldest age, completion throughput,
failure categories, start/end time, and action taken.

## Escalation and residual risk

Escalate if depth continues to rise, poison messages repeatedly return, or pending outbox
rows remain after an explicit replay-triggering action. The API has no autonomous outbox
poller. Local single-worker capacity does not establish production scaling behavior.
