# Persistence Architecture

The application has no local JSON runtime persistence. Telemetry lives in InfluxDB;
relational state and dense vectors live in PostgreSQL with pgvector.

## InfluxDB

InfluxDB stores telemetry points. MQTT topic names become measurements, payload tags
become Influx tags, fields become Influx fields, and the payload timestamp becomes the
point timestamp.

## PostgreSQL + pgvector

Active dense-vector material includes:

- `topic_embeddings`: authoritative stream-context vectors used by duplicate ANN
  search and stream-level recommendation evidence;
- `class_pair_embeddings`: independent `key`, `value`, `key_value`, and `schema`
  vectors for every tag/field pair;
- `class_pair_prototypes` and `class_stream_context_prototypes`: compatibility material
  for the older Saved-Class recommender.

System recommendation strategies consume `class_pair_embeddings` and
`topic_embeddings` directly. The `tag_value_centroid` baseline computes its centroids
in the decision layer from current tag `value` vectors; it does not own another vector
table or another embedding pipeline.

Vector tables use deterministic text identities, `vector(384)` embeddings, and cosine
HNSW indexes where nearest-neighbor search is required. JSONB payload indexes support
metadata filtering/deletion.

Relational source-of-truth tables include streams, Saved Classes and memberships,
duplicate identity/decisions, topic representation versions, recommendation
candidate/feedback records, versioned offline-learning model artifacts, and audited
shadow deployments/observations.

### Recommended candidate persistence

System recommendations use three relational tables:

- `recommended_class_candidates`: persistent identity for an exact strategy/member-set
  candidate and its current version;
- `recommended_class_candidate_versions`: immutable evidence snapshots for each
  monotonic candidate version;
- `recommended_class_feedback`: immutable user labels referencing an exact candidate
  version.

Candidate ids do not contain representation versions. If the same strategy returns the
same member set after evidence rematerialization, the candidate id remains stable and a
new candidate version is created when the evidence snapshot changes. A changed member
set is a new candidate identity.

Feedback rows copy the candidate evidence snapshot used for the action. The feedback
API never accepts user-supplied similarity scores. This keeps later training/evaluation
data tied to the evidence the user actually saw.

### Recommendation model registry

Offline learned models use three additional relational tables:

- `recommendation_model_versions`: immutable model identity, monotonic per-objective
  version, semantic dataset fingerprint, portable JSON artifact, and training report;
- `recommendation_model_evaluations`: immutable evaluation-gate reports keyed by a
  fingerprint of the explicit gate policy;
- `recommendation_model_events`: auditable registration, evaluation, offline approval,
  and retirement transitions.

Artifacts store StandardScaler statistics and Logistic Regression parameters as JSON,
not Python pickle blobs. The effective training dataset is fingerprinted independently
from the evaluation thresholds, so the same artifact can be evaluated later under a
new explicit policy without inventing another model version.

`OFFLINE_APPROVED` remains a governance state, not a deployment state. Approving a model
alone does not make runtime recommendation code consume it.

### Recommendation shadow deployment

Shadow mode adds three runtime-observation tables while preserving baseline ranking:

- `recommendation_shadow_deployments`: the explicitly activated model for each learning
  objective (`membership` or `candidate_quality`);
- `recommendation_shadow_deployment_events`: audited activation/deactivation history;
- `recommendation_shadow_observations`: learned scores for an exact persistent
  candidate version together with its unchanged baseline rank and the exact model ids
  used for scoring.

Only an `OFFLINE_APPROVED` model can be explicitly shadow-activated. Shadow activation
is separate from model approval and has `ranking_effect = none`: HDBSCAN/centroid still
determine the user-facing candidate set and order.

`recommended_class_feedback.shadow_observation_id` optionally links a later explicit
user action to the most recent observed shadow score for that exact candidate version.
The foreign key uses `ON DELETE SET NULL`; the copied immutable candidate evidence in
the feedback row remains authoritative even if observational shadow history is cleaned
up later.

Shadow evaluation uses only feedback attached to an observed exposure. Unshown
candidates are not synthesized as negatives. Repeated feedback is deduplicated with a
latest-explicit-label policy per model/candidate-version/target.

## ANN search

Cosine nearest-neighbor queries use pgvector's `<=>` operator:

```text
ORDER BY embedding <=> query_vector
LIMIT k
```

Returned similarity is `1 - cosine_distance`.

## Recommendation evidence contract

Pair evidence is versioned independently from recommendation strategy. Changing
HDBSCAN settings, changing the tag-value centroid threshold, adding another centroid
strategy, changing weights, or training a ranking model does not require rewriting
pair embeddings.

The representation contract changes only when the actual stored evidence shape or
renderer changes. Candidate versions are a separate decision/exposure history and do
not change the raw embedding contract.

## Embedding dimension

The current model contract is 384 dimensions (`BAAI/bge-small-en-v1.5` by default).
A different model dimensionality requires an explicit schema migration.

## Startup

PostgreSQL, MQTT, and InfluxDB are the required runtime services. Docker Compose uses
a PostgreSQL image with pgvector support and runs Alembic before backend startup.

## Historical schema

Older migration revisions may contain tables or columns no longer used by runtime
code, including retired tag-group tables/vector material. They remain migration
history unless a dedicated forward migration removes them. Current runtime code does
not read or write those retired structures, and current architecture documentation
describes active reads/writes rather than historical implementations.
