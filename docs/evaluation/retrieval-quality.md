# Retrieval and grounded-answer evaluation

The versioned v1 fixture corpus and questions live in
`apps/worker/tests/golden/retrieval-quality/v1/`. They use synthetic agreement
text, so they can be reused by local, CI, and provider-backed runs without
handling customer agreements.

Run an integration result through the provider-neutral evaluator with:

```sh
make retrieval-eval RETRIEVAL_EVAL_RESULTS=path/to/results.json
```

The result file must have the dataset `version` and one observation per question.
It can contain normalized observations or captured public API responses in
`runtime_observations`; the latter is normalized through the current search and
Q&A response adapter before evaluation.

```json
{
  "dataset_version": "1.0",
  "observations": [{
    "question_id": "termination-notice",
    "answer_status": "answered",
    "retrieved_sources": [{"agreement_id": "...", "anchor_id": "msa-termination", "source_checksum": "...", "source_version": "..."}],
    "citation_sources": [{"agreement_id": "...", "anchor_id": "msa-termination", "source_checksum": "...", "source_version": "..."}],
    "accepted_claims": [{"claim_id": "termination-notice", "citation_sources": [{"agreement_id": "...", "anchor_id": "msa-termination", "source_checksum": "...", "source_version": "..."}]}],
    "unauthorized_retrieved_sources": [],
    "latency_ms": 42.5,
    "cost_usd": 0.0012
  }]
}
```

Every source is scoped by agreement ID, checksum, source version, and anchor ID.
The runtime adapter accepts the public search response and the public
`QuestionTurnResponse` shape from Q&A. It verifies that cited source identities
were retrieved, and separately records any retrieved source not present in the
authorized source set. Identical anchors from different agreements or document
versions are never treated as the same source. The evaluator does not invoke a
model provider.

The report measures recall@5, citation precision and recall, unsupported
accepted claims (and rate), unauthorized and forbidden retrieval counts, expected
answer-state mismatches, p95 latency, and total reported provider cost. Initial
gates are recall@5 at least 0.80, citation precision exactly 1.0, and zero
unauthorized retrievals, forbidden retrievals, unexpected outcomes, or
unsupported accepted claims. Latency and cost are reporting-only. Once an
accepted retrieval baseline is recorded, recall cannot regress by more than five
percentage points.
