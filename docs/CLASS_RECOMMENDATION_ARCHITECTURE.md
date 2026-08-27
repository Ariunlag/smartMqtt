# System Recommended Class architecture

SmartMQTT has two class concepts:

1. **Saved Classes** are user-owned. `classes` and `class_topics` are their source of
   truth.
2. **Recommended Classes** are system-derived candidate topic groups. Discovery never
   inserts them into Saved Classes automatically.

## Core invariant: preserve evidence before deciding how to use it

Every tag and field is an independent key:value pair. Pair identity includes source
(`tag` or `field`), normalized key, datatype, topic, and representation version.

Each pair materializes the same independent evidence vectors:

- `key`
- `value`
- `key_value`
- `schema`

Each stream also has one `stream_context` vector.

No representation step fuses pair records or evidence channels. If one stream has
three tag pairs and two field pairs, five independent pair records are stored and each
record has four pair-evidence vectors.

`tag` and `field` are pair sources, not evidence channels. Numeric is datatype
metadata, not an additional semantic signal.

## Runtime flow

```text
MQTT message
  ├─ canonical duplicate-identity guard
  ├─ stream_context materialization
  ├─ InfluxDB persistence
  ├─ WebSocket broadcast
  └─ bounded evidence sidecar
       ├─ tag/field pair profiling
       ├─ key/value/key_value/schema embeddings per pair
       ├─ pgvector persistence
       └─ exploratory tag grouping from existing tag `value` vectors
```

The old tag-group feature no longer creates a second tag embedding. Its centroid
assignment consumes the same `value` vector already produced for each tag pair.

## Strategy boundary

Embedding generation is intentionally independent from recommendation policy.
`RecommendationStrategyInput` provides a strategy with the same immutable evidence
snapshot:

- active canonical topics,
- representation versions,
- pair embedding records,
- stream vectors,
- per-evidence symmetric topic similarities.

A recommendation strategy decides how to turn that evidence into candidate groups.
Changing strategy does not require rematerializing embeddings.

The current registered strategy is `independent_hdbscan`:

1. match pairs one-to-one only when source and datatype are compatible;
2. preserve individual key/value/key_value/schema cosine scores and coverage;
3. compute topic-pair similarity separately for every evidence id;
4. run HDBSCAN independently for each evidence id;
5. merge exact identical memberships as multi-evidence consensus.

There is no cross-evidence weighting in this strategy.

Future strategies can be added without changing the evidence contract, including:

- value-only or other evidence subsets,
- weighted evidence combinations,
- persistent candidate centroid/prototype matching,
- hybrid discovery + prototype matching,
- ranking learned from user actions.

Those strategies should consume the same stored raw evidence rather than create new
embedding pipelines.

## Centroids and prototypes

Centroids are a decision-layer representation, not a replacement for raw pair
vectors. A future Recommended Class prototype may maintain separate centroids for each
pair role and each evidence type:

```text
candidate pair role
  ├─ key centroid
  ├─ value centroid
  ├─ key_value centroid
  └─ schema centroid

candidate stream
  └─ stream_context centroid
```

Different pair roles must not be flattened into one global centroid.

The exploratory tag-group centroid is the narrow original form of this idea: it uses
the shared tag `value` vector and does not own separate embeddings.

## User feedback and learning

Future candidate actions should be persisted as versioned factual feedback. Useful
signals include keep, add, remove, reject, dismiss, and explicit Save as Class.

For learning/evaluation, preserve the evidence snapshot that produced each action:
individual evidence scores, coverage, strategy id, candidate version, and action. This
allows later experiments with calibrated weights or ranking models without changing
raw embeddings.

Human feedback on Recommended Classes must not silently mutate Saved Classes. Only an
explicit Save as Class or manual Saved-Class action may do that.

## Duplicate boundary

Duplicate detection remains an identity workflow.

- `PENDING`: both topics remain independently eligible.
- `NOT_DUPLICATE`: both remain independent.
- confirmed duplicate: the alias stops independent recommendation contribution.

The canonical root remains active.

## Persistence

PostgreSQL is the relational and dense-vector persistence boundary through pgvector.
InfluxDB stores telemetry time series. The active recommendation evidence lives in the
pair-vector and topic-vector tables and is versioned by the representation contract.

## API and UI

`GET /api/recommended-classes` accepts an optional `strategy` query parameter and
returns:

- candidates,
- available topics,
- active strategy metadata,
- registered strategy catalog,
- evidence catalog.

The dashboard keeps one Recommended Classes surface. With one strategy it shows the
active method. When multiple strategies are registered, the same surface presents a
method selector. A separate research/evaluation screen may later compare strategies
side-by-side, but end users should not receive duplicate top-level recommendation
features for each algorithm.

Saved Class CRUD remains under `/api/classes`. Older Saved-Class recommendation
endpoints remain compatibility-only and are not the dashboard Recommended Classes
workflow.
