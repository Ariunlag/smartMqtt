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
Recommended Class candidate snapshot
       ↓
explicit user feedback labels
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

## Persistent candidate snapshots

A recommendation returned to a user is now persisted before feedback is accepted.
Candidate persistence has two levels:

- `candidate_id` is deterministic for the exact `(strategy, member set)` and does not
  depend on representation versions;
- `candidate_version` is monotonic for that candidate id and changes whenever its
  evidence snapshot changes.

The immutable version snapshot records:

- strategy id;
- anchor and member topics;
- member representation versions;
- discovery evidence ids;
- topic-to-anchor evidence, coverage, and matched pairs;
- the representation contract version.

This means an evidence refresh can produce candidate version 2 while feedback against
version 1 still points to the exact evidence the user saw. A changed member set is a
new candidate identity; lineage across changing memberships is a separate future
problem rather than an implicit heuristic.

## User feedback and learning

The current UI collects explicit labels rather than silently changing embeddings or
centroids:

- `KEEP_TOPIC` — the member belongs in this candidate;
- `REMOVE_TOPIC` — the member does not belong in this candidate;
- `ACCEPT_CANDIDATE` — the candidate group is useful;
- `DISMISS_CANDIDATE` — the candidate group is not useful.

Each feedback event references `(candidate_id, candidate_version)` and stores a copy of
the immutable candidate evidence snapshot. User-supplied scores are never accepted by
the feedback API. Topic-level feedback must reference a member of that exact candidate
version.

Feedback is factual training/evaluation data. It does **not** immediately retrain the
embedding model, mutate a centroid, change candidate membership, or write into Saved
Classes. This keeps representation evidence stable and makes later experiments
reproducible.

The next learning layer can derive supervised features from these events, for example:

- `key`, `value`, `key_value`, `schema`, and `stream_context` scores;
- pair/source coverage;
- matched-pair counts;
- strategy id;
- positive/negative topic membership labels;
- positive/negative candidate usefulness labels.

Weighted or learned ranking is promoted only after offline evaluation against the
HDBSCAN and centroid baselines.

Human feedback on Recommended Classes must not silently mutate Saved Classes. A future
explicit Save as Class action may create a manual class, but that is a separate side
effect and feedback label.

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

System candidate/feedback relational tables are:

- `recommended_class_candidates`;
- `recommended_class_candidate_versions`;
- `recommended_class_feedback`.

Candidate-version rows and feedback events are durable factual records; raw vectors
remain in the shared pgvector evidence tables.

## API and UI

`GET /api/recommended-classes` accepts an optional `strategy` query parameter and
returns:

- candidates with `candidate_id` and `candidate_version`;
- available topics;
- active strategy metadata;
- registered strategy catalog;
- evidence catalog.

`POST /api/recommended-classes/{candidate_id}/feedback` records an explicit label for
an exact candidate version.

The dashboard keeps one Recommended Classes surface. With multiple strategies the same
surface presents a method selector. Candidate cards expose membership labels
(`Belongs`, `Doesn't belong`) and candidate usefulness labels (`Useful group`,
`Not useful`). A separate research/evaluation screen may later compare strategies
side-by-side, but end users should not receive duplicate top-level recommendation
features for each algorithm.

Saved Class CRUD remains under `/api/classes`. Older Saved-Class recommendation
endpoints remain compatibility-only and are not the dashboard Recommended Classes
workflow.