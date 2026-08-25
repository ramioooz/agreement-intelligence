# Local service objectives

These objectives make local regressions visible. They are not cloud service-level agreements.

| Operation | Local objective | Boundary |
|---|---:|---|
| Repository read | p95 under 500 ms | Authorized HTTP response |
| Filtered hybrid search | p95 under 1,000 ms | Authorized HTTP response; lexical fallback is valid |
| Q&A turn | p95 under 10,000 ms | Accepted response including explicit answer state |
| Upload acceptance | p95 under 1,000 ms | Upload stored and job accepted, not analysis completion |
| Queue to processing start | under 5 seconds at idle | SQS publish to durable processing state |
| Workflow decision acknowledgement | p95 under 1,000 ms | Durable decision/outbox acknowledgement |

All measurements must use synthetic or legally reusable documents, validate tenant isolation first, and distinguish synchronous acknowledgement from asynchronous completion. A failed provider may degrade search to lexical results and Q&A to `model_unavailable`; it must not produce a false successful provider result.

See [local performance checks](../../tests/performance/README.md) and [recovery checks](../../tests/resilience/README.md).
