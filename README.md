# InfluxAI Realtime IoT Hub

InfluxAI is a real-time IoT platform for MQTT telemetry ingestion, time-series
visualization, duplicate detection, tag grouping, user-defined Saved Classes, and
system-derived recommended class candidates.

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

A bounded recommendation sidecar creates pair-level embedding evidence without
blocking primary MQTT/Influx ingestion.

## Class concepts

SmartMQTT intentionally keeps two class concepts separate.

### Saved Classes

Saved Classes are created manually by the user through Class Builder. The user selects
individual topics/measurements, provides a class name, and owns membership. PostgreSQL
`classes` and `class_topics` are the source of truth.

### Recommended Classes

Recommended Classes are system-derived candidate topic groups. They are not copies of
Saved Classes and are not automatically inserted into `classes`/`class_topics`.

System discovery uses six independent evidence channels:

1. key
2. value
3. key + value
4. schema
5. numeric key when applicable
6. whole-stream context

Tags and fields remain independent pair sources. Candidate discovery runs per evidence
channel and identical member sets discovered by multiple channels are shown as
consensus reasons. The dashboard shows pair evidence, tag/field evidence, coverage,
and whole-stream context instead of explaining a recommendation with one fused
`Overall similarity` number.

See [architecture](docs/CLASS_RECOMMENDATION_ARCHITECTURE.md) and
[decisions](docs/CLASS_RECOMMENDATION_DECISIONS.md).

## Duplicate lifecycle

Duplicate detection remains separate from class discovery.

- `PENDING`: both topics remain active and independently eligible; the recommendation
  UI only marks pending review.
- `KEEP_BOTH` / `NOT_DUPLICATE`: both remain independent.
- confirmed duplicate: the losing topic becomes an alias and stops independent
  ingestion/recommendation contribution; canonical relationships are reconciled.

Topic ANN search uses the shared pgvector `topic_embeddings` table and cosine HNSW
index. Temporal evidence is combined by the duplicate service where enough aligned
points exist.

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
The PostgreSQL service uses `pgvector/pgvector:pg16` and migration
`0005_pgvector_embeddings` enables the vector extension and creates HNSW indexes.

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

Vector tables are created by Alembic and currently enforce 384-dimensional vectors:

- `topic_embeddings`
- `tag_key_value_embeddings`
- `tag_group_centroids`
- `class_pair_embeddings`
- `class_pair_prototypes` (legacy Saved-Class compatibility material)
- `class_stream_context_prototypes` (legacy Saved-Class compatibility material)

Each vector table has a cosine HNSW index plus a JSONB payload index. Duplicate ANN
queries use pgvector's `<=>` cosine-distance operator.

Relational source-of-truth state includes streams, user Saved Classes, duplicate
identity/decisions, tag-group relationships, topic representation versions, and audit
records.

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
| GET | `/api/recommended-classes` | System-derived class candidates with evidence |
| GET | `/api/class-recommendations/status` | Recommendation sidecar diagnostics |
| GET | `/api/groups` | Exploratory tag groups |
| GET | `/api/groups/{id}/topics` | Topics in a tag group |
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

The current pgvector schema is `vector(384)`. Changing embedding dimensionality
requires an explicit Alembic migration.

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

PostgreSQL must have pgvector available. InfluxDB and MQTT must also be reachable for
the complete runtime.

### Frontend

```bash
cd frontend
npm ci
npm test -- --run
npm run build
npm run dev
```

## Existing Qdrant deployments

The pgvector migration creates PostgreSQL vector tables; it does not copy historical
Qdrant bytes. Vector state is derived and active MQTT observations rematerialize
current topic/pair evidence. Export any historical vector-only artifacts that must be
retained before decommissioning an old Qdrant volume/service.

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
    class_recommendation/    Pair evidence and system candidate discovery
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
