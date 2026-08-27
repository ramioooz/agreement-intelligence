# Version comparison evaluation baseline

The frozen synthetic dataset is at
`apps/worker/tests/golden/version-comparison/v1/version-pairs.json`. It covers
matched, moved, split, merged, added, and removed structures, alongside
liability, termination, indemnity, obligation, governing-law, numeric, and
date-related changes.

Run a captured runtime result through the baseline with:

```sh
make version-comparison-eval VERSION_COMPARISON_EVAL_RESULTS=path/to/results.json
```

The evaluator consumes prepared observation JSON containing every case and only identifiers
and labels; the evaluation dataset never needs source document text. A direct adapter from
persisted runtime comparisons to that observation file is still deferred.

Separately, runtime comparison processing already persists and serializes typed
provider/model, latency, token, and cost provenance when those values exist.
Deterministic/no-provider comparison rows use an explicit empty safe provenance object, so
the response remains typed without inventing provider data.

The accepted release thresholds are:

- Unauthorized evidence count: `0`.
- Citation precision: `1.00`.
- Unsupported accepted claims: `0`.
- Deterministic change accuracy: at least `0.85`.
- Alignment F1: at least `0.80`.
- Critical material-change recall: `1.00`.

Provider-backed runs record validated provider/model and available usage, latency, and cost
metadata in the comparison provenance flow. Provider quality and operational metrics are
opt-in evidence and are deliberately not release gates in this deterministic baseline.
