# SmartMQTT — Adaptive Weighted Recommendation Experiment

This branch is a recommendation experiment. MQTT ingestion, InfluxDB telemetry, PostgreSQL/pgvector persistence, duplicate handling, Saved Classes, WebSocket updates, and the dashboard remain the shared SmartMQTT platform. The experimental part is the recommendation algorithm.

## Experiment

Branch: `experiment/recommendation-adaptive-weighted`

The active recommendation UI uses `/api/adaptive-recommendations`.

Semantic evidence is materialized through separate providers:

- `topic_text`
- `tag_key`
- `tag_value`
- `tag_key_value`
- optional `series_shape`

The recommender combines available evidence with weights, forms groups with complete-link style discovery, and can learn new weights from explicit recommendation interactions. This branch intentionally studies adaptive weighted recommendation behavior; results should not be treated as the baseline for the independent-evidence experiment.

## Recommendation surface

The dashboard surface is shared with every other recommendation experiment so the branches stay comparable. `frontend/src/components/recommendations/` holds one presentational panel (`RecommendationsPanel`) driven by one view model (`recommendationModel.ts`). The only branch-local file is `useRecommendationSource.ts`, which maps this branch's API onto that model.

Keep changes to the panel, the model, and `index.css` identical across experiment branches. Algorithm-specific wording belongs in the adapter, not the panel.

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

## Learning

This experiment stores recommendation events and environment-local learned models. The learner requires positive and negative examples across multiple contexts and only accepts a candidate update when held-out validation improves.

Relevant settings:

```text
RECOMMENDATION_ENVIRONMENT=default
ADAPTIVE_SIMILARITY_THRESHOLD=0.80
ADAPTIVE_LEARNING_INTERVAL=30
ADAPTIVE_MIN_LABELS=12
ADAPTIVE_EXACT_LIMIT=192
ADAPTIVE_NEIGHBORS=32
ADAPTIVE_SERIES_MODE=active
```

Set `ADAPTIVE_SERIES_MODE=off` when evaluating only semantic text channels.

## Tests

Backend:

```sh
cd backend
python -m pytest
```

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

This branch should stay focused on the adaptive-weighted recommendation hypothesis. Shared platform fixes should be kept algorithm-neutral where possible so experiments remain comparable.
