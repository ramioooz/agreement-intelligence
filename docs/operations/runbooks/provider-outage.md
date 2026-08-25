# Model-provider outage

## Trigger and impact

Provider smoke checks fail, worker logs record safe provider-unavailable reason codes,
semantic indexing is unavailable, or grounded answers return `model_unavailable`.
Lexical search and deterministic analysis remain available, but model enrichment and
new embeddings may be absent.

## Safe diagnostics

```bash
make stack-status
make provider-smoke
docker compose --project-name agreement-intelligence --env-file .env logs \
  --since 15m worker api
```

Do not print the API key, provider response body, prompts, or document content.

## Containment and recovery

1. Stop repeated manual retries; the gateway already applies bounded retries.
2. Confirm provider status, account quota, configured model, and network reachability.
3. If configuration is wrong, correct `.env` locally and restart API and worker.
4. After the provider recovers, run `make provider-smoke`.
5. Requeue failed agreement analysis from the agreement page. New search queries retry
   query embeddings automatically; previously failed document embeddings require
   reprocessing of the affected agreement.

## Verification and evidence

Verify provider smoke success, one newly processed agreement with model provenance,
semantic search results, and a cited Q&A response. Record provider, model/configuration
version, safe failure category, outage window, and recovered job IDs.

## Escalation and residual risk

Escalate sustained quota, authentication, or schema failures. The current local product
does not automatically backfill every historical document after provider recovery.
