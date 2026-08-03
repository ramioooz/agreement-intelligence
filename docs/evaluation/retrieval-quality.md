# Retrieval and grounded-answer evaluation

The versioned v1 fixture corpus and questions live in
`apps/worker/tests/golden/retrieval-quality/v1/`. They use synthetic agreement
text, so they can be reused by local, CI, and provider-backed runs without
handling customer agreements.

Run an integration result through the provider-neutral evaluator with:

```sh
make retrieval-eval RETRIEVAL_EVAL_RESULTS=path/to/results.json
```

The result file must have the dataset `version` and one observation per question:

```json
{
  "dataset_version": "1.0",
  "observations": [{
    "question_id": "termination-notice",
    "retrieved_anchor_ids": ["msa-termination"],
    "citation_anchor_ids": ["msa-termination"],
    "accepted_claims": [{"claim_id": "termination-notice", "citation_anchor_ids": ["msa-termination"]}],
    "unauthorized_retrieved_anchor_ids": [],
    "latency_ms": 42.5,
    "cost_usd": 0.0012
  }]
}
```

The retrieval adapter (#30) must provide ranked candidate anchor IDs after
tenant/workspace authorization and list every candidate that failed that
authorization in `unauthorized_retrieved_anchor_ids`. The answer adapter (#31)
must provide accepted material-claim IDs and their source anchor IDs. The
evaluator deliberately does not call either adapter, model gateway, or a
provider.

The report measures recall@5, citation precision and recall, unsupported
accepted claims (and rate), unauthorized retrieval count, p95 latency, and
total reported provider cost. Initial gates are recall@5 at least 0.80,
citation precision exactly 1.0, and zero unauthorized retrievals or unsupported
accepted claims. Latency and cost are reporting-only. Once an accepted retrieval
baseline is recorded, recall cannot regress by more than five percentage points.
