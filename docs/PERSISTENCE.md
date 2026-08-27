# Persistence Architecture

The application has no local JSON persistence. Each data type has one authoritative
database, and dense vectors now live beside relational metadata in PostgreSQL through
pgvector.

## InfluxDB

InfluxDB stores telemetry points. The MQTT topic is the measurement name; payload tags
become Influx tags, payload fields become Influx fields, and the payload timestamp
becomes the point timestamp.

## PostgreSQL + pgvector

PostgreSQL stores metadata, relationships, human decisions, and dense embedding
material. Alembic migration `0005_pgvector_embeddings` enables the `vector` extension
and creates HNSW cosine indexes for:

- `topic_embeddings`: normalized topic-plus-tag vectors used by duplicate ANN search
  and whole-stream recommendation context
- `tag_key_value_embeddings`: normalized tag key/value vectors
- `tag_group_centroids`: exploratory tag-group centroid vectors
- `class_pair_embeddings`: raw canonical pair/view vectors
- `class_pair_prototypes`: compact legacy Saved-Class pair centroids retained for
  compatibility while the system-candidate workflow is separated
- `class_stream_context_prototypes`: legacy Saved-Class context centroids retained for
  compatibility

Every vector table has a deterministic text identity, `vector(384)` embedding, JSONB
payload, HNSW cosine index, and GIN payload index. Vector lookup/deletion therefore no
longer scans an external collection in application code.

Relational source-of-truth tables include:

- `streams`: MQTT stream/subscription definitions
- `ignored_topics` and `detected_topics`: ingestion state
- `classes` and `class_topics`: user-owned Saved Classes and ordered membership
- `duplicates`: duplicate candidates and durable human review decisions
- `duplicate_canonical_topics`: canonical roots and confirmed aliases
- `tag_groups`, `tag_group_values`, and `tag_group_topics`: exploratory group metadata
- `topic_representations`: pair representation fingerprints and versions
- `class_recommendation_constraints`: legacy version-scoped rejection decisions
- `class_recommendation_dismissals`: legacy version-scoped hide state
- `class_recommendation_actions`: append-only factual action audit

The older `semantic_application_state` table remains legacy migration data. Production
code does not read or write it.

## ANN search

Cosine nearest-neighbor queries use pgvector's `<=>` operator and HNSW indexes. For
example, duplicate detection searches `topic_embeddings` with:

```text
ORDER BY embedding <=> query_vector
LIMIT k
```

The returned similarity is `1 - cosine_distance`, preserving the existing cosine-score
semantics used by duplicate detection.

## Embedding dimension contract

The current model contract is 384 dimensions (`BAAI/bge-small-en-v1.5` by default).
The schema enforces `vector(384)`. A future model with a different dimensionality must
ship with an explicit vector-schema migration rather than silently mixing dimensions.

## Startup and deployment

PostgreSQL, MQTT, and InfluxDB are the required runtime services. There is no separate
vector-database dependency. Docker Compose uses the pgvector PostgreSQL image and the
migration job runs `alembic upgrade head` before backend startup.

Existing PostgreSQL volumes remain PostgreSQL 16 data. Existing external-vector data
is derived evidence; active MQTT observations rematerialize topic/pair evidence into
pgvector. Operators who need historical vector-only artifacts should export them
before retiring the old vector service.

## Legacy JSON files

Files previously created under `backend/data/` are not read or written by the
application. They may be archived or removed after any desired one-time data migration.
