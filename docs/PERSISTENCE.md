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
- `tag_group_centroids`: exploratory tag-value centroids derived from the shared pair
  `value` evidence;
- `class_pair_prototypes` and `class_stream_context_prototypes`: compatibility material
  for the older Saved-Class recommender.

The pair evidence store is the source of embedding evidence for tag and field pairs.
Exploratory tag grouping does not create a second tag embedding collection at runtime.

Vector tables use deterministic text identities, `vector(384)` embeddings, and cosine
HNSW indexes where nearest-neighbor search is required. JSONB payload indexes support
metadata filtering/deletion.

Relational source-of-truth tables include streams, Saved Classes and memberships,
duplicate identity/decisions, exploratory tag-group membership, topic representation
versions, and audit/feedback records.

## ANN search

Cosine nearest-neighbor queries use pgvector's `<=>` operator:

```text
ORDER BY embedding <=> query_vector
LIMIT k
```

Returned similarity is `1 - cosine_distance`.

## Recommendation evidence contract

Pair evidence is versioned independently from recommendation strategy. Changing
HDBSCAN settings, adding a centroid strategy, changing weights, or training a ranking
model does not require rewriting pair embeddings.

The representation contract changes only when the actual stored evidence shape or
renderer changes.

## Embedding dimension

The current model contract is 384 dimensions (`BAAI/bge-small-en-v1.5` by default).
A different model dimensionality requires an explicit schema migration.

## Startup

PostgreSQL, MQTT, and InfluxDB are the required runtime services. Docker Compose uses
a PostgreSQL image with pgvector support and runs Alembic before backend startup.

## Historical schema

Older migration revisions may contain tables or columns no longer used by runtime
code. They remain migration history unless a dedicated forward migration removes
them. Current architecture documentation describes active reads/writes rather than
historical storage implementations.
