# Persistence Architecture

The application has no local JSON persistence. Each data type has one
authoritative database.

## InfluxDB

InfluxDB stores telemetry points. The MQTT topic is the measurement name;
payload tags become Influx tags, payload fields become Influx fields, and the
payload timestamp becomes the point timestamp.

## Qdrant

Qdrant stores embedding evidence and derived centroids:

- `topic_embeddings`: normalized topic-plus-tag representations
- `tag_key_value_embeddings`: normalized `key value` representations, with the
  source topic, key, and value in each point payload
- `tag_group_centroids`: centroid vectors used to assign tag representations
  to exploratory groups
- `class_pair_embeddings`: raw canonical pair/view vectors
- `class_pair_prototypes`: compact per-role class centroids
- `class_stream_context_prototypes`: one shared-context centroid per class

Point IDs are deterministic UUIDs, so reprocessing a topic or tag representation
updates the existing point.

## PostgreSQL

PostgreSQL stores metadata and relationships:

- `streams`: MQTT stream/subscription definitions
- `ignored_topics` and `detected_topics`: ingestion state
- `classes` and `class_topics`: saved classes and ordered membership
- `duplicates`: candidate scores and durable review decisions
- `tag_groups`, `tag_group_values`, and `tag_group_topics`: exploratory group
  metadata and relationships
- `topic_representations`: pair representation fingerprints and versions
- `class_recommendation_constraints`: version-scoped rejection decisions
- `class_recommendation_dismissals`: version-scoped hide state
- `class_recommendation_actions`: append-only factual action audit

The older `semantic_application_state` table is legacy migration data. Current
production code does not read or write it, and this migration preserves it
non-destructively.

Alembic owns schema creation; backend startup does not mutate schema.

## Startup

PostgreSQL and Qdrant are required services. The dependency monitor recovers
services in the background and restores MQTT subscriptions after broker
recovery. Docker Compose provisions persistent named volumes for all databases.

## Legacy JSON files

Files previously created under `backend/data/` are not read or written by the
application. They may be archived or removed after any desired one-time data
migration.
