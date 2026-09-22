# SmartMQTT · Influx Hub

> Architecture and future extension guide: [PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md).
> Update that document when adding recommendation strategies, learners, evidence providers,
> embedding models, or experiment branches.

A local IoT application for MQTT telemetry, live charts, duplicate-topic review,
and editable semantic Class recommendations. The stack runs FastAPI, React,
Mosquitto, InfluxDB and PostgreSQL with pgvector.

## Start the system

Requirements: Docker Desktop with Linux containers and internet access for the
first image build and embedding-model download.

```sh
docker compose up -d --build
docker compose ps
```

| Service | Address |
|---|---|
| Dashboard | http://localhost:3000 |
| API documentation | http://localhost:8000/docs |
| Readiness check | http://localhost:8000/api/health/ready |
| InfluxDB | http://localhost:8086 |
| MQTT broker | `localhost:1883` |

Compose runs Alembic migrations before starting the backend. PostgreSQL is available
inside the Docker network. The first backend startup may take longer while the
embedding model downloads. Compose defaults are for local development.

```sh
docker compose logs -f backend
docker compose stop
```

Stopping retains data. PostgreSQL, InfluxDB and the embedding cache use named
volumes; removing volumes deletes their contents.

## Run the live sensor publisher

Run one file to subscribe and publish all **56 sensors** every two seconds:

```sh
python -m pip install -r tools/publisher/requirements.txt
python tools/publisher/publish.py
```

In VS Code, open `tools/publisher/publish.py` and choose **Run Python File in Terminal**.
The system must already be running. Stop with **Ctrl+C**.

The [dataset](tools/publisher/dataset.json) is a plain list. Add a sensor by copying
one entry and editing its topic, tags and initial field readings:

```json
{
  "topic": "office/north/room101/climate",
  "tags": {
    "measurement": "room temperature",
    "unit": "celsius",
    "location": "north office"
  },
  "fields": {"temperature_c": 22.4}
}
```

Tags stay fixed; numeric fields change smoothly with small sensor noise. Each sensor
has 1–4 tags, according to its metadata. The script adds a fresh UTC timestamp,
subscribes every exact topic at `/api/subscribe`, publishes everything, and prints
each topic and payload. No generator, cohort selection or separate materialization
step is needed for the current UI.

Open **Recommendations → Refresh → Why?** to compare the current UI's four text
channels: **Topic, Tag keys, Tag values, Tag key + value**.

| Sensors | What to look for |
|---|---|
| 16 temperature, humidity, CO2 and power sensors | Same measurement described with different words, units, vendors and locations |
| 8 instruments on `factory/west/hvac/ahu7/supply-air/…` | Related topic paths, but different measured quantities: temperature, pressure, humidity, velocity, damper position, particles, sound and filter condition |
| 8 sensors in a barn, clinic, port, bakery, museum, station, mine and pool | Shared `monitored_equipment`, `installation_location`, `measured_property` keys; different equipment and measurements. Similar keys alone do not imply the same measurement class |
| 8 gas/water leak sensors | Different vendor keys, but synonymous string values describing methane leaks or water leaks |
| 8 battery/radio/tank sensors | `charge_state=low`, `cell_status=recharge required`, depleted/discharged battery descriptions versus healthy batteries and unrelated low radio/tank readings |
| 8 pipe/aeration sensors | `measured_medium=water, surrounding_medium=air` versus the reversed roles. Key sets and value sets match; the key/value associations differ |

For example, the pipe sensor measures **water in an air environment**; the submerged
aeration sensor measures **air in a water environment**. Comparing their keys or
values separately loses this distinction. Key–value text preserves the associations,
although the embedding model may still score both roles highly.

These examples expose different reasons for similarity; they do not force four
separate final groups. The current recommender combines evidence using its active
weights, threshold and available time-series evidence. Inspect the channel scores
before interpreting a group. Numeric telemetry does not enter the four text channels.
The publisher produces synthetic data; it does not prove classification accuracy.

Optional preview or short run:

```sh
python tools/publisher/publish.py --dry-run
python tools/publisher/publish.py --rounds 3
```

Without local Python:

```sh
docker compose run --rm --no-deps -v "./tools/publisher:/publisher:ro" backend python /publisher/publish.py --broker mqtt --backend http://backend:8000/api
```

Publisher checks:

```sh
python -m unittest discover -s tools/publisher -p test_publish.py
```

Previous datasets and benchmark tooling are preserved in ignored `.local/archive/`.
Existing database topics remain visible; changing this file does not delete earlier
published streams. The production recommendation algorithms are unchanged.

## MQTT message format

Subscribe to a topic in the MQTT tab or through `POST /api/subscribe`, then publish:

```json
{
  "tags": {
    "measurement": "air temperature",
    "location": "room 101"
  },
  "fields": {
    "temperature": 22.5
  },
  "timestamp": "2026-09-13T12:00:00Z"
}
```

The MQTT topic identifies the stream. Tags describe it; fields contain readings.
The publisher generates fresh timestamps automatically.

## How the current recommendations work

The dashboard uses `/api/adaptive-recommendations`. Four semantic channels are
materialized independently with `BAAI/bge-small-en-v1.5` by default:

| Channel | Input sent to the embedding model |
|---|---|
| `topic_text` | Topic path with `/` replaced by spaces |
| `tag_key` | Each tag key, normalized separately |
| `tag_value` | Each tag value, rendered separately |
| `tag_key_value` | Each associated `key: value` pair |

Field names and numeric readings are not fed into those four text channels.
For each channel, the comparator aligns evidence independently, computes similarity
and accounts for unmatched evidence through coverage. The final score is a weighted
mean over available channels; missing channels are excluded and weights renormalized.
The displayed similarity is not a calibrated probability of correct membership.

With only the four semantic channels active, initial weights are 25% each. The
optional `series_shape` provider compares aligned numeric windows from InfluxDB
using a Pearson shape score. When it is active, five initial weights are 20% each;
when its evidence is missing, the four semantic channels still have equal effective
weight. Constant, insufficient and stale series do not provide usable shape evidence.

Small collections use complete-linkage discovery. Larger collections use bounded
candidate retrieval followed by actual pair scoring and conservative group merges.
The approximate path can miss relationships and need not return identical groups.

### User edits and learning

- Review a suggested group, add/remove topics, confirm membership, undo an edit,
  or save the group as a Class.
- Create Classes manually through Class Builder. Membership changes also provide
  explicit positive or negative examples when usable evidence is available.
- Feedback retains the evidence associated with the action. Training runs in the
  background within the configured environment; one click does not guarantee a
  weight change.
- The learner needs positive and negative labels across multiple contexts. It
  holds out later groups, excludes overlapping reference topics from training,
  and activates new weights only when validation improves.
- Inspect **Learning details** for the active weights, evidence availability and
  training state. Key, value and key–value channels overlap, so learned weight
  percentages are not independent causal feature importance.

New evidence providers can register their own representation, version and comparator
in `adaptive_evidence.py`. The existing text embeddings need not be regenerated
solely because a weight changes.

### Duplicate identity

Duplicate detection is separate from Class recommendation. Pending and keep-both
pairs remain independent. Confirming a duplicate assigns a canonical topic and
stops the alias from contributing independently. Duplicate detection uses topic
vector search and temporal evidence when enough data is available.

### Storage and compatibility

MQTT ingestion writes telemetry to InfluxDB and emits dashboard events over WebSocket.
A bounded sidecar materializes recommendation evidence. PostgreSQL with pgvector
stores metadata, vectors, canonical identities, Classes, edits and learned weights.
There are no local JSON runtime databases and no separate vector-database service.

The adaptive tables are introduced by migration `0011_adaptive_recommendations`.
Older pair/schema recommendation endpoints, their persistence and operator scripts
remain for compatibility; they are not the dashboard's current adaptive workflow.
Keep the full migration history when starting a fresh database or upgrading one.

## Configuration

Compose reads overrides from a local `.env` file. Useful settings:

| Variable | Default | Meaning |
|---|---|---|
| `RECOMMENDATION_ENVIRONMENT` | `default` | Environment-scoped adaptive state |
| `ADAPTIVE_SIMILARITY_THRESHOLD` | `0.80` | Group similarity cutoff |
| `ADAPTIVE_LEARNING_INTERVAL` | `30` | Background refresh interval in seconds |
| `ADAPTIVE_MIN_LABELS` | `12` | Minimum usable labels before attempting learning |
| `ADAPTIVE_EXACT_LIMIT` | `192` | Topic count at which bounded retrieval takes over |
| `ADAPTIVE_NEIGHBORS` | `32` | Candidate neighbors per topic |
| `ADAPTIVE_SERIES_MODE` | `active` | `off`, `shadow` or `active` |
| `ADAPTIVE_SERIES_STEP` | `60` | Seconds per numeric bin |
| `ADAPTIVE_SERIES_BINS` | `32` | Number of bins per window |
| `ADAPTIVE_SERIES_MIN_POINTS` | `16` | Minimum usable points |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Text embedding model |
| `EMBEDDING_DEVICE` | `cpu` | Embedding device |

For a four-channel semantic-only run, put `ADAPTIVE_SERIES_MODE=off` in `.env`, then
run `docker compose up -d backend`. Existing semantic evidence is rematerialized
as needed for the provider configuration. Changing the provider catalog also changes
the learning manifest; previous weights are not assumed compatible.

Database credentials, MQTT and Influx connection settings are in `docker-compose.yml`
and `backend/config.py`. Keep populated environment files out of version control.
The supplied stack is for a trusted local environment; it has no public-facing
API authentication layer. The legacy vector tables use 384 dimensions, so changing
the embedding dimension requires a compatible schema migration.

## Tests and development

Backend (Python 3.11, virtual environment recommended):

```sh
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest
```

Frontend (Node.js 20):

```sh
cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
npm run dev
```

The normal backend suite uses test doubles; database integration checks require the
corresponding configured services. The isolated adaptive acceptance check runs with
real PostgreSQL/InfluxDB, creates its own temporary database and bucket, and cleans
those resources up:

```sh
docker compose run --rm --no-deps backend python tests/adaptive_stack_check.py
```

Additional lifecycle checks remain in `scripts/run_real_stack_acceptance.py` and
`docker-compose.acceptance.yml`. The acceptance runner uses namespaced topics and
may restart backend services; run it deliberately, not against an active demo.

To inspect migrations:

```sh
docker compose run --rm --no-deps migrate alembic current
docker compose run --rm --no-deps migrate alembic history
```

## Repository layout

```text
backend/
  api/                       HTTP and WebSocket routes
  models/                    Message and API contracts
  services/                  Ingestion, storage, duplicate and recommendation logic
  alembic/                   PostgreSQL migration history
  tests/                     Runtime regression and integration tests
frontend/
  src/                       React dashboard and component tests
scripts/                     Maintenance and acceptance commands
tools/publisher/             MQTT test publisher and its dataset
Dockerfile.backend           Backend image
Dockerfile.frontend          Dashboard image
docker-compose.yml           Local services and persistent volumes
```

## Contributors

- Ariunaa Tsegmed — ariunlag@gmail.com
- Ahmed Khaled — ahmedeeldin@gmail.com
