# ADR 0005: Use Durable Asynchronous Processing

## Status

Accepted

## Context

Parsing, OCR, classification, clause extraction, summarization, embedding,
indexing, comparison, and report generation may take seconds or minutes. They
depend on services that can throttle, time out, or fail temporarily. Executing
this work inside an HTTP request would consume API capacity, encourage unsafe
client retries, and lose progress when a process restarts.

The product also contains long-running review workflows that may pause for
human decisions over hours or days.

## Decision

Use durable SQS-compatible work queues and separately scalable Python workers.
Local development uses a protocol-compatible emulator. The AWS reference
deployment uses managed queues with dead-letter queues.

PostgreSQL remains the source of truth for business state, processing jobs,
checkpoints, workflow state, idempotency records, and audit history. Queue state
is not presented as authoritative business state.

### Transactional outbox

Commands that require asynchronous work write the business change, processing
job, audit event, and outbox event in one database transaction. A dispatcher
publishes pending outbox events and records attempts.

Publication may occur more than once. Consumers are idempotent.

### Message envelope

Messages contain:

- schema version;
- message and event identifiers;
- message type;
- tenant and resource identifiers;
- job identifier;
- correlation and causation identifiers; and
- creation timestamp.

Messages do not contain document text, prompts, credentials, access tokens, or
large processing artifacts.

### Delivery and retries

Standard queues provide at-least-once delivery. Workers:

1. validate the message schema;
2. verify the tenant and resource;
3. claim the job idempotently;
4. skip already completed work;
5. checkpoint successful stages;
6. persist results before acknowledgement; and
7. acknowledge only after durable success.

Transient failures use bounded retries with exponential backoff and jitter.
Permanent failures stop automatically. Exhausted messages move to a
dead-letter queue for inspected, authorized redrive.

### Queue topology

The first release uses queue families for:

- agreement processing;
- exports; and
- notifications.

Processing stages initially share an agreement-processing queue and use the
persisted job state machine. A stage receives a dedicated queue only when
measured scaling or isolation requires it.

### Human workflows

A persistent workflow runtime manages review state, checkpoints, and
human-approval pauses. Queues wake workers and deliver continuation requests;
they do not replace the workflow or business source of truth.

## Alternatives considered

### Process work inside API requests

This is simple but creates long requests, poor recovery, unsafe retries, and
tight coupling between interactive and processing capacity.

### PostgreSQL job table only

Workers could claim rows with `FOR UPDATE SKIP LOCKED`. This provides strong
transactional behaviour and minimal infrastructure, but requires custom
visibility, dead-letter, redrive, backpressure, and delivery operations.

### Redis-backed task queue

This has mature worker libraries and simple local operation. It is not selected
because the reference AWS deployment benefits from managed queue durability
and the project should exercise the same queue semantics locally and remotely.

### RabbitMQ

This provides flexible routing and delivery features but adds broker operation
and clustering without a current routing requirement.

### Kafka

This provides event retention, replay, partitions, and high throughput. The
first release does not require a general event stream, and adopting it would
introduce unnecessary operational and schema-management complexity.

## Consequences

### Positive

- API latency and worker capacity scale independently.
- Work survives API and worker restarts.
- Backpressure protects downstream providers.
- Dead-letter queues make poison work inspectable.
- Local and AWS deployments share delivery semantics.
- Job checkpoints provide clear user-visible progress.

### Negative

- Delivery is at least once, so idempotency is mandatory.
- Eventual consistency requires honest queued and processing UI states.
- Outbox dispatch, redrive, visibility timeouts, and queue alarms require
  operational support.
- Ordering is not guaranteed by standard queues.

### Required controls

- Define versioned message schemas.
- Use database uniqueness constraints as duplicate barriers.
- Keep sensitive and large payloads outside messages.
- Propagate correlation and causation identifiers.
- Set queue visibility timeouts from measured job duration and extend them
  safely for long jobs.
- Monitor queue depth, oldest-message age, retries, and dead-letter count.
- Use FIFO queues only after demonstrating a strict ordering requirement.
- Record adoption of an event-streaming platform in a new ADR.
