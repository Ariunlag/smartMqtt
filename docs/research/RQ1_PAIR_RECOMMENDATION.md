# RQ1 pair-level recommendation evaluation

RQ1 evaluates the same raw evidence contract used by runtime: independent tag/field
key:value pairs with `key`, `value`, `key_value`, and `schema` vectors plus the shared
`stream_context` vector.

The representation layer is fixed for an experiment run. Recommendation policy is a
separate variable. This allows the same dataset/evidence to compare:

- individual evidence types;
- evidence subsets;
- equal or calibrated weighted combinations;
- independent-evidence HDBSCAN;
- centroid/prototype matching;
- hybrid discovery + prototype matching;
- learned ranking once human-action labels exist.

The existing benchmark builds compact prototypes from CALIBRATION examples and ranks
VALIDATION or TEST examples with deterministic one-to-one pair matching. It reports
Top-1, Top-3, MRR, candidate/prototype coverage, latency, embedding calls, vector
counts, and storage estimates. Pair-role accuracy is only reported when the dataset
contains pair-role labels.

No benchmark condition should silently change the stored representation contract.
Weights and decision thresholds must be calibrated from evaluation data rather than
hard-coded into embedding generation.

Run with the configured model:

```powershell
python scripts/run_rq1_benchmark.py `
  --dataset backend/tests/fixtures/rq1_controlled_smoke_v1.json `
  --output-dir docs/results/rq1-pair `
  --split VALIDATION
```

The deterministic hash backend exists only for smoke tests and does not replace the
configured embedding model.
