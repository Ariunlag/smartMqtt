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
       └─ pgvector persistence

stored evidence snapshot
  ├─ pair vectors
  ├─ stream vectors
  └─ per-evidence topic similarities
       ↓
registered recommendation strategy
       ↓
Recommended Class candidates
```

There is one pair-evidence pipeline. Recommendation algorithms do not create their own
copies of tag or field embeddings.

## Strategy boundary

`RecommendationStrategyInput` provides every strategy with the same immutable evidence
snapshot:

- active canonical topics,
- representation versions,
- independent pair embedding records,
- stream vectors,
- per-evidence symmetric topic similarities.

A strategy decides how to turn that evidence into candidate groups. Changing strategy
does not require rematerializing embeddings.

Two baseline strategies are currently registered.

### Independent evidence (HDBSCAN)

`independent_hdbscan`:

1. matches pairs one-to-one only when source and datatype are compatible;
2. preserves individual `key`, `value`, `key_value`, `schema` scores and coverage;
3. computes topic-pair similarity separately for every registered evidence id;
4. runs HDBSCAN independently for each evidence id;
5. merges exact identical memberships as multi-evidence consensus.

There is no cross-evidence weighting in this strategy.

### Tag value centroid

`tag_value_centroid` is the original centroid baseline expressed over the same current
evidence store:

1. iterate every pair independently;
2. keep only pairs whose source is `tag`;
3. read that pair's already-materialized `value` vector;
4. compare it with current centroids using cosine similarity;
5. assign it to the nearest centroid when the configured threshold is reached,
   otherwise start a new centroid;
6. recompute the centroid from its assigned raw tag-value vectors;
7. emit topic groups meeting the configured minimum topic count.

It creates no extra embeddings and owns no separate persistence/UI workflow.

## Future experiments

The same evidence contract supports future strategies such as:

- value-only, key-only, or other evidence subsets;
- weighted evidence combinations;
- persistent candidate centroid/prototype matching;
- hybrid discovery + prototype matching;
- ranking learned from user actions.

Centroids and weights belong in the decision layer. Raw pair vectors remain independent
so experiments can be compared over the same evidence.

A future Recommended Class prototype may maintain separate centroids for each semantic
pair role and evidence type rather than flattening all pairs into one global centroid.

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
InfluxDB stores telemetry time series. Active system-recommendation evidence lives in
pair-vector and topic-vector tables and is versioned by the representation contract.
Algorithm selection does not change those stored representations.

## API and UI

`GET /api/recommended-classes` accepts an optional `strategy` query parameter and
returns:

- candidates,
- available topics,
- active strategy metadata,
- registered strategy catalog,
- evidence catalog.

The dashboard keeps one Recommended Classes surface. With multiple strategies the same
surface presents a method selector. A separate research/evaluation screen may later
compare strategies side-by-side, but end users should not receive duplicate top-level
recommendation features for each algorithm.

Saved Class CRUD remains under `/api/classes`. Older Saved-Class recommendation
endpoints remain compatibility-only and are not the dashboard Recommended Classes
workflow.
