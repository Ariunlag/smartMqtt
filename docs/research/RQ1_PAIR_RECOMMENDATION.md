# RQ1 pair-level class recommendation evaluation

RQ1 now evaluates the same unit and representations used by production:
independent key:value pairs with `key`, `value`, `key_value`, `schema`, and
numeric-only `numeric_key`, plus the separate shared `stream_context` channel.

The benchmark builds compact class prototypes from CALIBRATION examples and
ranks VALIDATION or TEST examples with production one-to-one matching. It
reports Top-1, Top-3, MRR, candidate coverage, prototype coverage, latency,
embedding calls, vector counts, and a storage estimate. Pair matching accuracy
is reported as unavailable unless a dataset supplies pair-role labels.

Conditions include every channel independently and the production equal-mean
fusion. The benchmark does not choose or tune production weights. Confirmed
duplicate aliases are excluded by the dataset loader and cannot cross splits;
keep-both topics remain independent.

Run with the real configured model:

```powershell
python scripts/run_rq1_benchmark.py `
  --dataset backend/tests/fixtures/rq1_controlled_smoke_v1.json `
  --output-dir docs/results/rq1-pair `
  --split VALIDATION
```

The deterministic hash backend exists only for smoke tests and does not replace
the production embedding model.
