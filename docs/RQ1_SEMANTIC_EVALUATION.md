# RQ1 semantic representation evaluation

## Research question

How should MQTT/JSON stream representations capture both a key's semantic type
and its relationship to its value, and what are the accuracy and computational
cost trade-offs?

This document specifies an experiment. It does not redefine SmartMQTT's
production six-view representation, consensus, decision thresholds, duplicate
identity behavior, MQTT ingestion, embedding model, or feedback semantics.

## Hypotheses

1. Keys should distinguish streams that have similar numeric values but
   different semantic types.
2. Raw numeric values may add observation noise without improving semantic
   class recommendation.
3. Key-only text may split manufacturer-specific synonyms more than a
   key/value relationship representation.
4. Multiple views help only when their evidence is sufficiently independent;
   correlated views should not be treated as six independent successes.
5. More vectors and richer text can improve quality only at measurable
   construction, embedding, scoring, memory, and storage cost.

The benchmark reports uncertainty. It must not claim superiority when observed
differences are within bootstrap or repeated-run noise.

## Representation conditions

The first six conditions call `RepresentationBuilder` directly. Given its
deterministically ordered profile entries, their exact texts are:

| Production condition | Exact construction |
| --- | --- |
| `VALUE_ONLY` | normalized values joined with `" | "` |
| `KEY_ONLY` | normalized keys joined with `" | "` |
| `KEY_VALUE` | `key: value` units joined with `" | "` |
| `SCHEMA` | `key: structural_type` units joined with `" | "` |
| `NUMERIC_KEY_ONLY` | numeric keys alone; nonnumeric `key: value` units |
| `TOPIC_KEY_VALUE` | normalized topic followed by the exact `KEY_VALUE` text |

Normalization, tag-before-field ordering, and structural types therefore remain
the production definitions in
`backend/services/semantic/representations.py` and
`backend/services/semantic/stream_profiler.py`.

The isolated research conditions are:

| Experimental condition | Deterministic construction |
| --- | --- |
| `APPROACH1_KEY_VALUE_UNITS` | concatenated `key:value` units |
| `APPROACH2_INDEPENDENT` | one key text and one value text, fused by mean, configured weighted mean, or concatenation |
| `APPROACH3_TYPED_RELATION` | numeric field: `key measurement value`; nonnumeric field: `key is value`; tag: `key value` |
| `NUMERIC_RAW` | `key: raw_value` |
| `NUMERIC_TYPE` | numeric entries become `key: numeric`; other entries retain values |
| `NUMERIC_BUCKET` | configured numeric boundaries produce only `key: numeric bucket N` |

Typed descriptions and buckets are templates, not runtime model generations.
Buckets are ordinal and do not invent domain terms such as "low temperature."
Domain labels are valid only in a separately declared dataset condition with
externally justified boundaries.

No synonym dictionary is used. A future dictionary experiment must be named,
configured, and reported as a separate condition.

## Dataset contract and isolation

The machine-readable schema is
`docs/schemas/rq1_benchmark_dataset_v1.schema.json`. A record contains:

- stable stream and source record IDs;
- topic, tags, and fields or schema;
- semantic class label;
- `CALIBRATION`, `VALIDATION`, or final held-out `TEST` split;
- `CONTROLLED` or `REAL` source kind;
- optional canonical duplicate disposition;
- optional human-confirmed authoritative label.

The current algorithms have no trainable representation step, so prototype
construction and parameter selection use `CALIBRATION`. `VALIDATION` compares
candidate configurations. `TEST` is executed once only after thresholds,
fusion, templates, and static weights are frozen. The loader rejects logical
stream IDs, source record IDs, or topics that cross split boundaries.

Confirmed Phase 2 aliases are excluded before scoring. Their canonical record
is counted once. `KEEP_BOTH` records remain independent examples. Every run
records input, retained, excluded-alias, and retained-`KEEP_BOTH` counts.

The included smoke fixture is controlled test data, not an RQ1 result dataset.
It exercises:

- `temp`, `temperature`, `temperature_celsius`, and `heat_level`;
- voltage and pressure streams sharing temperature-like values;
- `sensor_id` and `building_id` ambiguity;
- missing tags, irrelevant manufacturer/location tags, and topic variation;
- schema-equivalent and `KEEP_BOTH` streams;
- separately labeled small `REAL`-kind records to verify stratified reporting.

Full RQ1 reporting must replace or supplement it with licensed, traceable real
IoT datasets. Controlled and real metrics are never pooled into an unlabeled
number.

## Decisions and quality metrics

Evaluation thresholds are passed through `RQ1DecisionConfig`; they are not
production thresholds. Cosine scores remain similarities and are never called
probabilities or confidence percentages.

For every source kind and condition, persisted results contain:

- accuracy, macro precision, macro recall, and macro F1;
- deterministic per-class precision, recall, F1, and support;
- deterministic confusion labels and matrix;
- UNKNOWN precision and recall;
- UNCERTAIN rate and decided coverage;
- known-class false-positive rate on unseen examples;
- top-1, top-3, and mean reciprocal rank for known examples;
- seeded percentile-bootstrap intervals for major metrics.

Offline diagnostics optionally include the expected class, automated state and
class, decision reason, per-view similarities and top candidate, top-1 votes,
and similarity margin. They are not exposed by production APIs.

Automated metrics always use the decision captured before feedback. A
`HUMAN_CONFIRMED` authoritative label is reported separately after feedback and
can never turn an incorrect automated prediction into an automated success.

## Single-view and multi-view ablation

Selected variants are evaluated individually. With `--include-multiview`, the
same frozen evidence is compared using equal vote and similarity averaging.
The multi-view run also adds calibrated static weights. By default these are
derived deterministically from per-view leave-one-out top-1 accuracy on
`CALIBRATION` only. `--static-weights` can instead supply already-frozen
calibration-derived weights. Resolved weights are persisted and cannot use
validation or test evidence.

The run artifact includes a pairwise top-candidate agreement matrix and Pearson
correlation of per-example, per-class similarity sequences. High agreement or
correlation is evidence of redundancy, not proof that a view is useless.
Production equal-view consensus is not changed by these experiments.

## Cost, storage, scale, and centroid checks

Each condition records representation construction, embedding, scoring, and
end-to-end timing with mean and median. P95 is reported from at least 20 samples
and P99 from at least 100. The CLI records model cold-load time separately from
steady-state calls.

Artifacts also record computed embedding vectors, stored fused vectors,
dimension per view, approximate float32 bytes per stream, and a Qdrant vector
count estimate. Approach 2 therefore exposes the cost of its two embedding
inputs even when they fuse into one stored vector.

Optional scale sizes compare brute-force stream-vector scoring with class
centroid scoring. The dependency-free run labels Qdrant ANN as not exercised;
a real-stack run must report it separately where applicable. The intended full
baseline sizes are 100, 1,000, and 10,000; the smoke command deliberately omits
them.

For every class and view, incrementally accumulated centroids are compared with
a fresh arithmetic mean. Member count, maximum and mean absolute error, and L2
error are persisted. This check does not modify production centroid logic.

## Artifacts and reproducible CLI

From the repository root:

```powershell
python -m scripts.run_rq1_benchmark `
  --dataset backend/tests/fixtures/rq1_controlled_smoke_v1.json `
  --output-dir artifacts/rq1-smoke `
  --seed 42 `
  --variants VALUE_ONLY,KEY_ONLY,KEY_VALUE,SCHEMA,NUMERIC_KEY_ONLY,TOPIC_KEY_VALUE `
  --include-multiview
```

The default backend is the configured production sentence-transformer model,
used only by the evaluation process. Local/CI smoke validation can pass
`--embedding-backend deterministic-hash`; that model is clearly recorded and
must never be used for research conclusions.

The CLI writes:

- `rq1_run.json`: metadata, summaries, agreement/correlation, centroid checks,
  and optional scale rows;
- `rq1_predictions.jsonl`: one offline prediction record per condition/example;
- `rq1_ablation.csv`: generated quality/cost/storage comparison rows.

Run metadata includes UTC timestamp, Git commit, dataset version and SHA-256,
model, device, normalization ownership, condition and threshold configuration,
seed, split, and duplicate filtering statistics. Documentation tables must be
generated from these persisted files; benchmark numbers must not be typed by
hand.

## Full experiment protocol

1. Validate provenance, labels, canonical identities, and split isolation.
2. Load the embedding model and record cold-load time.
3. Build class prototypes only from `CALIBRATION` canonical records.
4. Use `VALIDATION` to choose decision thresholds, Approach 2 fusion,
   deterministic bucket boundaries, and any static view weights.
5. Freeze the complete configuration and its hash.
6. Execute the held-out `TEST` split once, preserving controlled and real
   strata.
7. Repeat timing runs or use sufficient sample sizes; bootstrap quality metrics
   with fixed seeds.
8. Generate every table or plot from the JSON/JSONL/CSV artifacts.
9. Run 100/1,000/10,000 scale paths and real Qdrant ANN separately from the
   unit-test smoke benchmark.

## Threats to validity

- Controlled names may resemble embedding-model pretraining vocabulary and are
  not representative of all MQTT deployments.
- Topic tokens can leak class hints; `TOPIC_KEY_VALUE` must be compared with
  topic-neutral conditions and adversarial topic names.
- Manufacturer naming, units, missing metadata, multilingual keys, and class
  ambiguity may differ materially across real datasets.
- Similarity thresholds and static weights can overfit small calibration sets.
- Runtime timings depend on hardware, model cache state, batch size, process
  contention, and Qdrant topology.
- Approximate float32 storage excludes index, payload, replication, and database
  overhead.
- Bootstrap intervals quantify sample variability, not every source of model or
  dataset uncertainty.
- Human-confirmed state measures workflow correctness after feedback, not
  automated classifier quality.

No production promotion is justified until the complete controlled and real
held-out experiment supports it.
