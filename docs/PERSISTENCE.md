# Persistence Architecture

The application has no local JSON persistence. Each data type has one
authoritative database.

## InfluxDB

InfluxDB stores telemetry points. The MQTT topic is the measurement name;
payload tags become Influx tags, payload fields become Influx fields, and the
payload timestamp becomes the point timestamp.

## Qdrant

Qdrant stores semantic vectors in three collections:

- `topic_embeddings`: normalized topic-plus-tag representations
- `tag_key_value_embeddings`: normalized `key value` representations, with the
  source topic, key, and value in each point payload
- `tag_group_centroids`: centroid vectors used to assign tag representations
  to semantic groups

Point IDs are deterministic UUIDs, so reprocessing a topic or tag representation
updates the existing point.

## PostgreSQL

PostgreSQL stores metadata and relationships:

- `streams`: MQTT stream/subscription definitions
- `ignored_topics` and `detected_topics`: ingestion state
- `classes` and `class_topics`: saved classes and ordered membership
- `duplicates`: candidate scores and durable review decisions
- `tag_groups`, `tag_group_values`, and `tag_group_topics`: semantic group
  metadata and relationships

The backend creates these tables and indexes idempotently during startup.

## Startup

PostgreSQL and Qdrant are required services. The FastAPI backend waits for
PostgreSQL, Qdrant, MQTT, and InfluxDB before restoring MQTT subscriptions.
Docker Compose provisions persistent named volumes for all three databases.

## Legacy JSON files

Files previously created under `backend/data/` are not read or written by the
application. They may be archived or removed after any desired one-time data
migration.
