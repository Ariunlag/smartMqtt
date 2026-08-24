# InfluxAI Realtime IoT Hub

InfluxAI is a real-time IoT platform for MQTT telemetry ingestion, time-series
visualization, semantic topic analysis, duplicate detection, tag grouping, and
user-defined topic classes.

The application uses FastAPI and React, with a strict separation between
telemetry, embeddings, and relational metadata:

| Data | Database |
|---|---|
| Sensor telemetry and historical time series | InfluxDB |
| Topic, tag key/value, and group-centroid embeddings | Qdrant |
| Streams, classes, duplicate decisions, groups, and relationships | PostgreSQL |

The application does not use local JSON files for runtime persistence.

## Architecture

```text
IoT publishers
      |
      v
Mosquitto MQTT
      |
      v
FastAPI ingestion pipeline
      |
      +--> InfluxDB   telemetry and time-series queries
      +--> Qdrant     semantic vectors and nearest-neighbor search
      +--> PostgreSQL metadata and relationships
      |
      +--> WebSocket live events
                |
                v
        React + Zustand dashboard
```

### MQTT ingestion flow

1. A publisher sends a JSON message to a subscribed MQTT topic.
2. The backend validates the payload.
3. A previously unseen topic is embedded with
   `BAAI/bge-small-en-v1.5`.
4. Topic and tag key/value vectors are written to Qdrant.
5. Topic, class, duplicate, and tag-group relationships are recorded in
   PostgreSQL.
6. Telemetry is written to InfluxDB using the MQTT topic as the measurement
   name.
7. The message and semantic updates are broadcast to connected dashboards over
   WebSocket.

## Services

| Service | Technology | Local address |
|---|---|---|
| Dashboard | React, Vite, Nginx | http://localhost:3000 |
| Backend API | FastAPI, Uvicorn | http://localhost:8000 |
| API documentation | FastAPI OpenAPI | http://localhost:8000/docs |
| InfluxDB | InfluxDB 2.7 | http://localhost:8086 |
| Qdrant | Qdrant 1.15 | http://localhost:6333 |
| Qdrant dashboard | Qdrant UI | http://localhost:6333/dashboard |
| MQTT | Eclipse Mosquitto | `localhost:1883` |
| MQTT WebSocket | Eclipse Mosquitto | `localhost:9001` |
| PostgreSQL | PostgreSQL 16 | Internal Docker network |

## Semantic research foundation

The repository contains isolated research components for deterministic stream
profiling, six textual stream representations, multi-representation embedding,
Qdrant representation persistence, semantic pipeline orchestration, and stream
semantic class centroid, similarity, and ranking operations.

These components are foundation modules and are not yet fully integrated into
the default production MQTT ingestion path. For the intended architecture and
implementation status, see the [Semantic Roadmap](docs/SEMANTIC_ROADMAP.md).
For the rationale behind major architecture choices, see
[Semantic Decisions](docs/SEMANTIC_DECISIONS.md).

## Quick start with Docker

Requirements:

- Docker Desktop with the Linux container engine running
- At least several gigabytes of available disk space
- Internet access for the first image build and embedding-model download

Build and start the complete stack:

```bash
docker compose up -d --build
```

Check service status:

```bash
docker compose ps
docker compose logs -f backend
```

Run the non-destructive real-stack acceptance workflow after startup changes:

```bash
python -m scripts.run_real_stack_acceptance --run-id local-001
```

See the [Real-stack acceptance runbook](docs/REAL_STACK_ACCEPTANCE.md) for
prerequisites, diagnostics, credential handling, and outage/recovery checks.

The backend health endpoint should report all dependencies as `true`:

```bash
curl http://localhost:3000/api/health
```

Expected response:

```json
{
  "PostgresClient": true,
  "QdrantClient": true,
  "MQTTClient": true,
  "InfluxClient": true
}
```

Stop the containers without deleting database data:

```bash
docker compose down
```

Delete containers and all database volumes:

```bash
docker compose down -v
```

The `-v` command permanently removes PostgreSQL, Qdrant, and InfluxDB data.

## MQTT payload

Messages must be valid JSON with `fields`, `tags`, and an ISO 8601
`timestamp`:

```json
{
  "fields": {
    "temperature": 22.5,
    "humidity": 61
  },
  "tags": {
    "location": "lab",
    "sensor": "environment"
  },
  "timestamp": "2026-06-29T03:10:00Z"
}
```

Example subscription:

```bash
curl -X POST http://localhost:3000/api/subscribe \
  -H "Content-Type: application/json" \
  -d '{"topic":"building/lab/environment"}'
```

Example publication:

```bash
mosquitto_pub \
  -h localhost \
  -p 1883 \
  -t building/lab/environment \
  -m '{"fields":{"temperature":22.5},"tags":{"location":"lab"},"timestamp":"2026-06-29T03:10:00Z"}'
```

## Persistence model

### InfluxDB

- Bucket: `smartHub`
- Measurement: MQTT topic
- Tags: payload `tags`
- Fields: payload `fields`
- Timestamp: payload `timestamp`
- Recent-message window: one hour
- Duplicate-correlation window: up to 100 numeric points from 24 hours

### Qdrant

Qdrant collections are created lazily when the first semantic record is
processed:

- `topic_embeddings`
- `tag_key_value_embeddings`
- `tag_group_centroids`

Point IDs are deterministic, so reprocessing the same semantic entity updates
its existing vector.

### PostgreSQL

The one-off `migrate` service applies the Alembic schema before the backend
becomes ready. The schema includes:

- `streams`
- `ignored_topics`
- `detected_topics`
- `classes`
- `class_topics`
- `duplicates`
- `tag_groups`
- `tag_group_values`
- `tag_group_topics`

See [Persistence Architecture](docs/PERSISTENCE.md) for more detail.

## Main API endpoints

All REST routes use the `/api` prefix.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Dependency health |
| GET | `/api/topics` | Active MQTT subscriptions |
| POST | `/api/subscribe` | Subscribe to a topic |
| POST | `/api/unsubscribe` | Unsubscribe from a topic |
| GET | `/api/measurements` | InfluxDB measurement names |
| GET | `/api/timeseries` | Historical measurement points |
| GET | `/api/messages` | Recent MQTT-shaped messages |
| GET | `/api/duplicates` | Pending duplicate candidates |
| POST | `/api/duplicate-confirm` | Resolve a duplicate candidate |
| GET/POST | `/api/classes/` | List or create classes |
| PUT/DELETE | `/api/classes/{name}` | Update or delete a class |
| GET | `/api/groups` | Semantic tag groups |
| GET | `/api/groups/{id}/topics` | Topics related to a group |
| WebSocket | `/ws` | Live MQTT and semantic events |

## Configuration

Docker Compose supplies the required service configuration. For manual backend
development, copy `backend/.env.example` to `backend/.env` and configure:

```dotenv
MQTT_BROKER=localhost
MQTT_PORT=1883

INFLUX_URL=http://localhost:8086
INFLUX_BUCKET=smartHub
INFLUX_ORG=influxai
INFLUX_TOKEN=CHANGE_ME

POSTGRES_DSN=postgresql://influxai:CHANGE_ME@localhost:5432/influxai

QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DEVICE=cpu

ID_THRESH=0.90
MIN_POINTS=10
DUPE_CHECK_DELAY=60
GROUP_TAG_THRESH=0.85
```

## Local development

### Backend

Python 3.11 is recommended:

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
python main.py
```

PostgreSQL, Qdrant, InfluxDB, and MQTT must be reachable before FastAPI
finishes startup.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

The Vite development server proxies `/api` and `/ws` to
`http://localhost:8000`.

## Verification

The Docker stack has been tested for:

- deterministic frontend and backend image builds
- dependency health checks
- frontend-to-backend Nginx proxying
- class create, update, delete, and restart persistence
- MQTT subscription restoration after restart
- MQTT-to-InfluxDB telemetry ingestion
- topic and tag key/value embedding persistence in Qdrant
- PostgreSQL topic and tag-group relationships
- historical time-series and recent-message API responses

Useful checks:

```bash
docker compose config --quiet
docker compose ps
```

```bash
cd frontend
npm run build
npm run lint
```

```bash
uv run --no-project --with ruff ruff check backend --exclude backend/.venv
```

## Known limitations

- The first backend start downloads and loads the embedding model, so startup
  can take longer than subsequent health checks.
- FastAPI startup/shutdown currently uses deprecated `on_event` handlers and
  should be migrated to a lifespan handler.
- Semantic processing and database access run inside the main backend process;
  heavier workloads should move embedding and duplicate detection to workers.
- Authentication and authorization are not implemented.
- The included credentials and anonymous MQTT configuration are for local
  development only.
- Frontend dependency auditing currently reports packages requiring review.
- Existing scripts under `test/` are research utilities rather than a complete
  automated regression suite.

## Project structure

```text
backend/
  api/                  FastAPI routes
  models/               Pydantic request and response models
  services/
    database/           PostgreSQL and Qdrant clients
    duplicate/          Duplicate scoring
    embedding/          Sentence-transformer integration
    influx/             InfluxDB client
    mqtt/               MQTT client and handler pipeline
    store/              Database-backed repositories

frontend/
  src/
    components/         Dashboard feature components
    hooks/              Bootstrap and WebSocket hooks
    services/           API and chart adapters
    store/              Zustand state

docs/                   Architecture and engineering notes
test/                   Research and publishing utilities
```

## Contributors

- Ariunaa Tsegmed — ariunlag@gmail.com
- Ahmed Khaled — ahmedeeldin@gmail.com
