# SmartMQTT — Independent Evidence Recommendation Experiment

This branch is a recommendation experiment. MQTT ingestion, InfluxDB telemetry, PostgreSQL/pgvector persistence, duplicate handling, Saved Classes, WebSocket updates, and the dashboard remain the shared SmartMQTT platform. The experimental part is how recommendation candidates are discovered and ranked.

## Experiment

Branch: `experiment/recommendation-independent-evidence`

The dashboard uses the system-derived recommendation API and keeps evidence channels independent during discovery.

Primary evidence:

- `key`
- `value`
- `key_value`
- `schema`
- `stream_context`

Each HDBSCAN evidence space produces its own candidate classes. Identical topic membership discovered by different evidence channels remains separate and receives a different candidate identity. This preserves evidence provenance and allows feedback to distinguish, for example, a useful key-based group from an unhelpful value-based group with the same members.

The tag-value centroid baseline remains available as a separate strategy over stored tag `value` embeddings.

Conceptually:

```text
key            -> HDBSCAN -> candidates
value          -> HDBSCAN -> candidates
key_value      -> HDBSCAN -> candidates
schema         -> HDBSCAN -> candidates
stream_context -> HDBSCAN -> candidates

tag value      -> centroid -> baseline candidates
```

No learned weight is used to create these memberships.

## Learning

Candidate generation stays unsupervised and deterministic for a fixed evidence snapshot and configuration.

Feedback is recorded against immutable candidate versions:

- `KEEP_TOPIC`
- `REMOVE_TOPIC`
- `ACCEPT_CANDIDATE`
- `DISMISS_CANDIDATE`

Learning is downstream of discovery. It can evaluate/rank already-generated candidates through the existing offline, shadow, and live-ranking infrastructure without changing candidate membership.

Saved Classes remain a separate user-managed concept and are not the source of recommendation membership labels in this experiment.

## Evidence materialization

Tag and field pairs remain independent. For each pair SmartMQTT stores four representations:

```text
key
value
key_value
schema
```

Changing numeric field readings do not rematerialize semantic pair embeddings. Numeric telemetry remains in fields. Each stream also has one `stream_context` embedding.

## Run

```sh
docker compose up -d --build
docker compose ps
```

Dashboard: `http://localhost:3000`

API docs: `http://localhost:8000/docs`

MQTT broker: `localhost:1883`

InfluxDB: `http://localhost:8086`

## Publisher

```sh
python -m pip install -r tools/publisher/requirements.txt
python tools/publisher/publish.py --rounds 3
```

The publisher subscribes exact topics through `/api/subscribe`, keeps tags stable, changes numeric fields over time, and publishes fresh UTC timestamps.

Example MQTT payload:

```json
{
  "tags": {
    "measurement": "air temperature",
    "location": "room 101"
  },
  "fields": {
    "temperature": 22.5
  },
  "timestamp": "2026-09-14T12:00:00Z"
}
```

Tags describe stable metadata. Numeric telemetry belongs in `fields`.

## Recommendation API

Primary endpoint:

```text
GET /api/recommended-classes
```

The strategy can be selected through the existing strategy parameter. The response includes the evidence catalog, strategy catalog, immutable candidates, discovery channels, shadow diagnostics, and live-ranking diagnostics.

## Tests

Backend:

```sh
cd backend
python -m pytest
```

Important experiment coverage includes:

- different evidence channels with identical membership remain separate candidates
- candidate identity includes discovery evidence
- primary pair-evidence processing remains authoritative
- secondary adaptive observation cannot break the primary recommendation path

Frontend:

```sh
cd frontend
npm test -- --run
npm run build
```

Publisher:

```sh
python -m unittest discover -s tools/publisher -p test_publish.py
```

## Repository layout

```text
backend/            FastAPI, recommendation, persistence, duplicate logic
frontend/           React dashboard
tools/publisher/    MQTT dataset and publisher
scripts/            maintenance and acceptance commands
```

This branch should stay focused on the independent-evidence recommendation hypothesis. Shared platform fixes should remain algorithm-neutral where possible so recommendation experiments can be compared on the same infrastructure and data.
