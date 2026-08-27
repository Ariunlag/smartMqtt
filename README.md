# InfluxAI Realtime IoT Hub

InfluxAI is a real-time IoT platform for MQTT telemetry ingestion, time-series
visualization, duplicate detection, evidence-based grouping, user-defined Saved
Classes, and system-derived Recommended Classes.

Runtime persistence is split by responsibility:

| Data | Database |
|---|---|
| Sensor telemetry and historical time series | InfluxDB |
| Relational metadata, human decisions, and dense vectors | PostgreSQL + pgvector |

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
      +--> InfluxDB                  telemetry and time-series queries
      +--> PostgreSQL + pgvector     metadata, identity, ANN/vector evidence
      +--> WebSocket                 live dashboard events
                |
                v
        React + Zustand dashboard
```

A bounded evidence sidecar creates pair-level embeddings without blocking primary
MQTT/Influx ingestion.

## One evidence pipeline

Every tag and field is preserved as an independent key:value pair. For every pair the
same registry-defined evidence is materialized independently:

1. `key`
2. `value`
3. `key_value`
4. `schema`

Each stream also has one `stream_context` vector. Pair vectors are never fused during
representation generation. A stream with three tag pairs therefore has three
independent pair records, each with four vectors, plus the stream-context vector.

`tag` and `field` are pair sources, not extra evidence channels. Numeric is datatype
metadata, not a separate recommendation signal.

Exploratory tag grouping reuses the tag pair's existing `value` vector for centroid
assignment. It does not create a second tag-specific embedding pipeline.

## Recommendation strategies

Recommended Classes consume the same stored evidence through a strategy boundary.
The current production strategy is `independent_hdbscan`: each evidence type is
clustered independently and identical topic memberships are merged as consensus.
There is no cross-evidence weighting in this strategy.

The representation layer is intentionally strategy-agnostic. Future centroid,
weighted, evidence-subset, and learned-ranking strategies can consume the same raw
pair evidence, stream vectors, per-evidence similarities, and coverage without
regenerating embeddings.

`GET /api/recommended-classes` returns both the evidence catalog and the active
strategy metadata. The optional `strategy` query parameter selects a registered
strategy. The dashboard keeps one Recommended Classes view; when multiple strategies
are registered, the same view exposes a method selector rather than duplicating the
feature into separate top-level tabs.

## Class concepts

### Saved Classes

Saved Classes are created manually by the user through Class Builder. PostgreSQL
`classes` and `class_topics` are their source of truth.

### Recommended Classes

Recommended Classes are system-derived candidate topic groups. They are not copies of
Saved Classes and are not automatically inserted into `classes`/`class_topics`.

The dashboard shows candidate members, discovery evidence, matched pair coverage,
tag/field evidence, pair-level scores, and stream context. It does not present one
fused `Overall similarity` as the explanation.

See [architecture](docs/CLASS_RECOMMENDATION_ARCHITECTURE.md) and
[decisions](docs/CLASS_RECOMMENDATION_DECISIONS.md).

## Duplicate lifecycle

Duplicate detection is an identity workflow separate from class recommendation.

- `PENDING`: both topics remain active and independently eligible.
- `KEEP_BOTH` / `NOT_DUPLICATE`: both remain independent.
- confirmed duplicate: the losing topic becomes an alias and stops independent
  ingestion/recommendation contribution.

Duplicate ANN search uses the shared `topic_embeddings` pgvector table and cosine HNSW
index. Temporal evidence is combined where enough aligned points exist.

## Services

| Service | Technology | Local address |
|---|---|---|
| Dashboard | React, Vite, Nginx | http://localhost:3000 |
| Backend API | FastAPI, Uvicorn | http://localhost:8000 |
| API documentation | FastAPI OpenAPI | http://localhost:8000/docs |
| InfluxDB | InfluxDB 2.7 | http://localhost:8086 |
| MQTT | Eclipse Mosquitto | `localhost:1883` |
| MQTT WebSocket | Eclipse Mosquitto | `localhost:9001` |
| PostgreSQL + pgvector | PostgreSQL 16 / pgvector | Internal Docker network |

There is no separate runtime vector-database service.

## Quick start

Requirements:

- Docker Desktop with Linux containers
- several GB of available disk space
- internet access for the first image build and embedding-model download

Start the stack:

```bash
docker compose up -d --build
docker compose ps
```

The one-off migration container runs `alembic upgrade head` before backend startup.
The PostgreSQL service uses `pgvector/pgvector:pg16`.

Check backend logs:

```bash
docker compose logs -f backend
```

Run real-stack acceptance after lifecycle/persistence changes:

```bash
python -m scripts.run_real_stack_acceptance --run-id local-001
```

Stop without deleting data:

```bash
docker compose down
```

Delete all persistent volumes only when intentionally resetting local data:

```bash
docker compose down -v
```

## MQTT payload

Messages must contain `fields`, `tags`, and an ISO-8601 timestamp:

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

## PostgreSQL + pgvector persistence

Active vector material includes:

- `topic_embeddings`
- `tag_group_centroids`
- `class_pair_embeddings`
- `class_pair_prototypes` (legacy Saved-Class recommendation compatibility)
- `class_stream_context_prototypes` (legacy Saved-Class recommendation compatibility)

Vector tables use cosine HNSW indexes and JSONB payload indexes where applicable.
The current vector dimension is 384. Changing embedding dimensionality requires an
explicit Alembic migration.

See [Persistence Architecture](docs/PERSISTENCE.md).

## Main API endpoints

All REST routes use `/api`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health/live` | Process liveness |
| GET | `/api/health/ready` | Required dependency readiness |
| GET | `/api/topics` | Active MQTT subscriptions |
| POST | `/api/subscribe` | Subscribe to a topic |
| POST | `/api/unsubscribe` | Unsubscribe from a topic |
| GET | `/api/measurements` | InfluxDB measurement names |
| GET | `/api/timeseries` | Historical measurement points |
| GET | `/api/duplicates` | Pending duplicate candidates |
| POST | `/api/duplicate-confirm` | Resolve duplicate identity |
| GET/POST | `/api/classes/` | List/create user Saved Classes |
| PUT/DELETE | `/api/classes/{name}` | Update/delete a Saved Class |
| GET | `/api/recommended-classes` | System candidates; optional `strategy` query |
| GET | `/api/class-recommendations/status` | Evidence sidecar diagnostics |
| GET | `/api/groups` | Exploratory groups derived from shared tag-value evidence |
| GET | `/api/groups/{id}/topics` | Topics in an exploratory group |
| WebSocket | `/ws` | Live MQTT/dashboard events |

Older Saved-Class matching endpoints remain temporarily for compatibility but are not
the dashboard Recommended Classes workflow.

## Configuration

Core settings include:

```dotenv
MQTT_BROKER=localhost
MQTT_PORT=1883

INFLUX_URL=http://localhost:8086
INFLUX_BUCKET=smartHub
INFLUX_ORG=influxai
INFLUX_TOKEN=CHANGE_ME

POSTGRES_DSN=postgresql://influxai:CHANGE_ME@localhost:5432/influxai

EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DEVICE=cpu
EMBEDDING_DIMENSION=384

ID_THRESH=0.90
MIN_POINTS=10
DUPE_CHECK_DELAY=60
GROUP_TAG_THRESH=0.85
CLASS_RECOMMENDATION_QUEUE_MAXSIZE=1000
SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE=2
SYSTEM_RECOMMENDATION_MIN_SAMPLES=1
```

## Local development

### Backend

Python 3.11 is recommended:

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
pytest
python main.py
```

### Frontend

```bash
cd frontend
npm ci
npm test -- --run
npm run build
npm run dev
```

## Project structure

```text
backend/
  api/                       FastAPI routes
  models/                    API/domain models
  services/
    database/                PostgreSQL + pgvector adapters
    duplicate/               Duplicate scoring/canonicalization
    embedding/               Sentence-transformer integration
    influx/                  InfluxDB client
    mqtt/                    MQTT client and handler pipeline
    class_recommendation/    Evidence, matching, and strategy layer
    store/                   Persistence repositories

frontend/
  src/
    components/              Dashboard features
    hooks/                   Bootstrap/WebSocket hooks
    services/                API/chart adapters
    store/                   Zustand state

docs/                        Architecture, persistence, research notes
```

## Contributors

- Ariunaa Tsegmed — ariunlag@gmail.com
- Ahmed Khaled — ahmedeeldin@gmail.com
