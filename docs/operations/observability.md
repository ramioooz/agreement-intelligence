# Local observability

The default stack exports only to the Collector debug exporter. To enable the local Langfuse mirror, copy the `LANGFUSE_*` entries from `docker/langfuse/.env.example` into `.env`, create a Langfuse project, and set `LANGFUSE_OTLP_AUTH` to the Base64 form of its public-key/secret-key pair.

```sh
docker compose --env-file .env -f compose.yaml -f compose.observability.yaml --profile observability up -d
```

Open `http://localhost:3001`, upload a synthetic agreement, and use the API response correlation header to locate its opaque W3C trace ID in the Collector/Langfuse trace view. Inspect request, queue, worker, retrieval, and model spans for aggregate latency, retry, token, cost, retrieval, evaluation, and workflow measurements.

Only the fixed operational schema is exported: operation/outcome, timing, retry counts, token/cost totals, result counts, and workflow state. Document text, prompts, provider output, credentials, emails, subjects, titles, raw identifiers, and request bodies are excluded before exporter handoff. Langfuse mirrors this safe telemetry; it is not the authority for prompts, configuration, or evaluation baselines.
