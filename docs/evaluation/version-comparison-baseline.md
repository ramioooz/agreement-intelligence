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

The runtime adapter is intentionally deferred until comparison contracts are
stable. A result must contain every case and report only identifiers and labels;
the evaluation dataset never needs source document text.

The accepted release thresholds are:

- Unauthorized evidence count: `0`.
- Citation precision: `1.00`.
- Unsupported accepted claims: `0`.
- Deterministic change accuracy: at least `0.85`.
- Alignment F1: at least `0.80`.
- Critical material-change recall: `1.00`.

Provider quality, latency, and cost are recorded by the runtime comparison
provenance flow when it is implemented. They are deliberately not release gates
in this deterministic baseline.
