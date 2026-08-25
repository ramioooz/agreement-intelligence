# Bad model or AI-configuration release

## Trigger and impact

Evaluation quality regresses, schema validation failures increase, citations fail
validation, cost/latency changes materially, or a promoted model configuration produces
unsafe output.

## Safe diagnostics

```bash
make provider-smoke
make retrieval-eval RETRIEVAL_EVAL_RESULTS=/path/to/results.json
make version-comparison-eval VERSION_COMPARISON_EVAL_RESULTS=/path/to/results.json
docker compose --project-name agreement-intelligence --env-file .env logs \
  --since 15m worker api
```

Compare model, prompt/schema, configuration, and index versions. Use frozen synthetic
evaluation data; never paste production agreements into an incident ticket.

## Containment and recovery

1. Stop promotion of the affected immutable configuration version.
2. Restore the previously approved provider/model/configuration values in `.env` or
   activate the last approved registry version.
3. Restart API and worker if runtime environment values changed.
4. Rerun the relevant evaluation and provider smoke checks.
5. Reprocess only agreements affected by the bad version; immutable prior artifacts
   and provenance remain available for comparison.

## Verification and evidence

Confirm gates return to their accepted baselines, new artifacts name the restored
configuration, citations validate, and deterministic findings were not weakened.
Record immutable version IDs, evaluation report checksum, safe metrics, and operator.

## Escalation and residual risk

Escalate unsupported claims, cross-tenant evidence, or guardrail bypass immediately.
Local evaluation does not prove every production-domain input is safe.
