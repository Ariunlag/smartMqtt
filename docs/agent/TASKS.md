# Smart-MQTT++ Task List

This file tracks the next development tasks. Each task should be implemented in a separate feature branch.

## Current Stable Branch

`dev-prod`

## Recommended Feature Branches

### 1. feature/docker-deployment

Goal:
Add Docker-based local deployment.

Scope:
- Add backend Dockerfile.
- Add frontend Dockerfile.
- Add docker-compose.yml.
- Add Mosquitto service.
- Add InfluxDB service.
- Add `.env.example`.

Do not:
- Add PostgreSQL yet.
- Add Qdrant yet.
- Refactor the backend.

### 2. feature/readme-cleanup

Goal:
Make the GitHub README professional and public-facing.

Scope:
- Rename project publicly as Smart-MQTT++.
- Add short project description.
- Add architecture summary.
- Add quick-start instructions.
- Link to docs.

### 3. feature/multi-broker

Goal:
Support multiple MQTT broker configurations.

Scope:
- Add broker configuration model.
- Allow multiple broker entries.
- Preserve current single-broker behavior.
- Add source_id or broker_id metadata.

Do not:
- Rewrite the MQTT client completely unless required.

### 4. feature/http-ingestion

Goal:
Add HTTP telemetry ingestion endpoint.

Scope:
- Add POST /api/ingest.
- Normalize incoming telemetry into the same internal format as MQTT messages.
- Store numeric values in InfluxDB.
- Trigger semantic processing when appropriate.

### 5. feature/dataset-replay

Goal:
Add dataset replay for benchmark and demo use.

Scope:
- Add CSV replay script.
- Publish replayed data through MQTT or direct HTTP ingestion.
- Support configurable replay rate.

### 6. feature/benchmark

Goal:
Add reproducible performance evaluation.

Scope:
- Measure ingestion throughput.
- Measure InfluxDB write latency.
- Measure embedding latency.
- Measure duplicate detection latency.
- Generate benchmark output files.

### 7. feature/metadata-db

Goal:
Move metadata persistence from JSON files to a database.

Scope:
- Evaluate SQLite or PostgreSQL.
- Preserve JSON mode for local demo if needed.
- Store topics, classes, duplicates, feedback, and tag groups.

### 8. feature/security-hardening

Goal:
Prepare for external deployment.

Scope:
- Restrict CORS.
- Add API authentication.
- Add MQTT username/password support.
- Add payload size validation.
- Add better error handling and logging.
