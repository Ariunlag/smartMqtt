# Codebase Engineering Review: influxai_v2

> Historical snapshot (2026-04-09). This review predates the pair-level class
> recommendation refactor and must not be used as the current architecture.
> See `docs/ARCHITECTURE_OVERVIEW.md`.

Date: 2026-04-09  
Reviewer mode: code-driven architecture review (facts from code + explicit inferences)

---

## A. Project Summary

### What the system does

**Fact (from code):**
- Backend is a FastAPI service that starts MQTT + InfluxDB clients, exposes REST APIs under `/api/*`, and serves a WebSocket endpoint `/ws`.
  - Entry: `backend/main.py`
  - Startup orchestration: `backend/services/service_manager.py`
- MQTT messages are parsed, persisted to InfluxDB, semantically embedded, checked for duplicate topics, grouped by tag similarity, and pushed to UI over WebSocket events.
  - MQTT pipeline: `backend/services/mqtt/client.py`, `backend/services/mqtt/handlers/*.py`
  - Duplicate logic: `backend/services/dupe_manager.py`, `backend/services/duplicate/duplicate_service.py`
  - Grouping logic: `backend/services/groups_manager.py`, `backend/services/tag_manager.py`
- Frontend is React + Vite + Zustand dashboard for topic subscription, duplicate management, group exploration, class saving, and real-time charting.
  - App entry: `frontend/src/main.tsx`, `frontend/src/App.tsx`

**Inference:**
- This is a real-time IoT telemetry intelligence dashboard with a focus on semantic metadata analysis (not only timeseries plotting).

### Who/what interacts with it

**Fact:**
- MQTT broker publishes sensor-like payloads (`fields`, `tags`, `timestamp`) to topics: `backend/services/mqtt/client.py`.
- FastAPI REST consumers (frontend via axios) call topic/data/duplicate/class/group endpoints: `frontend/src/services/*.ts`.
- WebSocket clients (frontend hook) listen for `mqtt_message`, `topic`, `duplicate`, and `group` events: `frontend/src/hooks/useWebSocket.ts`.
- InfluxDB is used for numeric telemetry persistence/query: `backend/services/influx/client.py`, `backend/services/query_manager.py`.

### Main engineering purpose

**Fact:**
- Combine live ingestion + persisted timeseries + embedding-based semantic reasoning into one operator UI.

**Inference:**
- Purpose is to support operational observability plus assisted curation (detect duplicate sensors, build reusable classes, discover tag clusters).

---

## B. Architecture Overview

### High-level components

1. **Backend API and lifecycle**
- `backend/main.py`
- Wires routers, CORS, startup/shutdown hooks.

2. **Service orchestration**
- `backend/services/service_manager.py`
- Registers MQTT handlers, connects MQTT/Influx clients, resubscribes saved topics, health-checks services.

3. **MQTT ingestion pipeline**
- `backend/services/mqtt/client.py`
- Handler chain registration: `backend/services/mqtt/handler_setup.py`
- Handlers:
  - `TopicHandler` -> detect first-seen topic, kick off embeddings/grouping/dupe detection, broadcast topic event
  - `InfluxHandler` -> write numeric payload to Influx
  - `Broadcaster` -> broadcast raw message to WebSocket clients

4. **Storage layer**
- InfluxDB for telemetry: `backend/services/influx/client.py`
- JSON file stores for metadata state (`topic_store`, `detected_topic_store`, `dupe_store`, `class_store`, `tagset_store`, `topic_embedding_store`): `backend/services/store/*.py`

5. **Semantic processing**
- Embedding model wrapper (SentenceTransformer): `backend/services/embedding/sentence_transformer.py`
- Topic/tag embedding orchestration: `backend/services/embedding_manager.py`
- Duplicate score (cosine + Pearson correlation): `backend/services/duplicate/duplicate_service.py`
- Grouping/tag-set logic: `backend/services/tag_manager.py`, `backend/services/groups_manager.py`

6. **Frontend presentation + state**
- React component modules under `frontend/src/components/*`
- Zustand stores:
  - MQTT state: `frontend/src/store/useMqttStore.ts`
  - Influx/class state: `frontend/src/store/useInfluxStore.ts`
  - Duplicates: `frontend/src/store/useDuplicateStore.ts`
  - Groups: `frontend/src/store/useGroupStore.ts`
- WebSocket event binding: `frontend/src/hooks/useWebSocket.ts`

### Architecture style

**Fact:**
- Modular monolith with event-driven ingestion internals and API-first UI integration.

**Inference:**
- It is not microservices; concerns are separated by service modules inside one backend process.

### How components connect

- MQTT broker -> `MQTTClient._on_message` -> handler chain.
- Handlers write to Influx + JSON stores + `WebSocketManager.broadcast`.
- REST endpoints expose query/control over stores and Influx query layer.
- Frontend bootstraps via `/api/health`, then fetches baseline state, then subscribes to `/ws` for live deltas.

---

## C. End-to-End Flow

### Flow 1: New MQTT topic/message ingestion

1. MQTT payload arrives at `MQTTClient._on_message` (`backend/services/mqtt/client.py`).
2. Payload must parse into `MQTTMessage(topic, fields, tags, timestamp)` (`backend/models/mqtt_message.py`).
3. Handlers execute in configured order (`backend/services/mqtt/handler_setup.py`):
- `TopicHandler.handle_message` (`backend/services/mqtt/handlers/topic_handler.py`)
  - If topic is ignored -> returns `False` and stops pipeline.
  - If topic first-seen in `detected_topic_store`:
    - store topic
    - call `embedding_manager.process_new_topic(topic, message.tags)`
    - broadcast event `{event_type: "topic", data: {measurement: topic}}`
- `InfluxHandler.handle_message` (`backend/services/mqtt/handlers/influx_handler.py`)
  - write point to Influx via `InfluxManager`.
- `Broadcaster.handle_message` (`backend/services/mqtt/handlers/ws_handler.py`)
  - broadcast event `{event_type: "mqtt_message", data: ...}`.

4. During semantic processing (`backend/services/embedding_manager.py`):
- Flatten topic+tags and embed via SentenceTransformer.
- Persist embedding to `topic_embedding_store`.
- Embed tag values and pass to `tag_manager.process_tag`.
- Trigger:
  - `groups_manager.update_for_topic(...)` for group updates + group WS events
  - `dupe_manager.check_new_topic(...)` for delayed duplicate candidate detection.

5. Frontend receives WS event in `useWebSocket` (`frontend/src/hooks/useWebSocket.ts`) and updates matching Zustand stores.

### Flow 2: Duplicate confirmation workflow

1. UI loads pending duplicates via `GET /api/duplicates` (`backend/api/duplicates.py`).
2. User action posts `POST /api/duplicate-confirm` with action (`KEEP_BOTH` or `UNSUBSCRIBE`).
3. `dupe_manager.confirm_duplicate` or `dupe_manager.keep_both` updates status (`backend/services/dupe_manager.py`).
4. For `UNSUBSCRIBE`, backend unsubscribes `topic_b` through `TopicManager.unsubscribe`.

### Flow 3: Build/save class and graphing workflow

1. Frontend fetches available measurements from `GET /api/measurements` (`backend/api/data.py`).
2. User selects measurements in `ClassBuilder` (`frontend/src/components/classes/*.tsx`).
3. Store fetches timeseries via `GET /api/timeseries` and renders charts (`frontend/src/store/useInfluxStore.ts`, `frontend/src/components/graphs/RealtimeGraph.tsx`).
4. User saves class through `POST /api/classes/` (`backend/api/classes.py`) -> persisted in `class_store.json`.

---

## D. API / Endpoint Analysis

Base prefix: `/api` for REST, `/ws` for websocket.

### Health
- `GET /api/health`
- File: `backend/api/health.py`
- Purpose: returns service connection health map by service class name.

### Topic control
- `GET /api/topics`
- `POST /api/subscribe`
- `POST /api/unsubscribe`
- File: `backend/api/topic.py`
- Purpose: manage MQTT subscriptions and list subscribed topics.

### Data query
- `GET /api/measurements`
- `GET /api/timeseries` (expects query alias `names[]` in backend signature)
- `GET /api/messages`
- File: `backend/api/data.py`
- Purpose: fetch measurement names, time-series data, and recent messages.

### Duplicate management
- `GET /api/duplicates`
- `POST /api/duplicate-confirm`
- File: `backend/api/duplicates.py`
- Purpose: review and resolve duplicate candidates.

### Class management
- `GET /api/classes/`
- `POST /api/classes/`
- `PUT /api/classes/{name}`
- `DELETE /api/classes/{name}`
- File: `backend/api/classes.py`
- Purpose: CRUD-ish management for named measurement sets.

### Group management
- `GET /api/groups`
- `GET /api/groups/{set_id}/topics`
- File: `backend/api/groups.py`
- Purpose: inspect semantic tag groups and member topics.

### WebSocket
- `WS /ws`
- File: `backend/api/socket.py`
- Purpose: push live events (`mqtt_message`, `topic`, `duplicate`, `group`) to frontend.

### Request/response pattern notes

**Fact:**
- Most routes use Pydantic response models (`backend/models/api_models.py`).

**Not evident from codebase:**
- No explicit OpenAPI YAML file checked into repo (FastAPI auto-generates docs).

---

## E. Data Model / State Flow

### Main entities

- `MQTTMessage`: `topic`, `tags`, `fields`, `timestamp` (`backend/models/mqtt_message.py`)
- `DupeRecord`: `topics[2]`, `score`, `status` (`backend/models/api_models.py`)
- `ClassRecord`: `name`, `topics[]`
- `TagSetRecord`: `id`, `tags[]` (+ internal `centroid`, `topics` in JSON store)
- Measurement series response: `measurement`, `points[{timestamp,value}]`

### Relationships

- Topic -> many Influx points.
- Topic -> one stored embedding record in `topic_embedding_store`.
- Tag values -> grouped into tag sets (`tagset_store`).
- Duplicate pair -> links two topics with confidence score/status.
- Class -> user-curated many-topic bundle.

### Lifecycle/state transitions

- Duplicate: `PENDING -> CONFIRMED_DUPLICATE` or `NOT_DUPLICATE`.
- New topic lifecycle:
  - observed by MQTT -> stored in detected topics -> embedded -> maybe grouped/marked duplicate -> broadcast to UI.
- Frontend state is persisted partially via Zustand `persist` middleware (`useMqttStore`, `useInfluxStore`, `useDuplicateStore`).

---

## F. Key Design Decisions

### 1) Hybrid storage (InfluxDB + JSON files)

**Why it appears chosen:**
- Keep heavy telemetry in TSDB, lightweight metadata in local JSON for quick iteration.

**Strengths:**
- Fast prototyping.
- Clear split of concerns.
- Easy local portability.

**Tradeoffs:**
- JSON file stores are not transaction-safe under concurrent/multi-instance deployments.
- Harder to scale horizontally without shared metadata database.

### 2) Handler chain for MQTT processing

**Why:**
- Separates topic discovery, persistence, and broadcasting concerns.

**Strengths:**
- Extensible pipeline (new handlers can be appended).

**Tradeoffs:**
- Pipeline order is behavior-critical.
- `return False` short-circuit can suppress downstream work (intentional for ignored topics, but can hide side effects).

### 3) Semantic duplicate/grouping with embeddings

**Why:**
- Duplicate detection based on meaning and signal correlation, not only exact strings.

**Strengths:**
- Better matching across naming variations.

**Tradeoffs:**
- Model load/runtime cost (SentenceTransformer + torch).
- Model behavior introduces non-deterministic or threshold-sensitive outcomes.

### 4) WebSocket push + REST baseline fetch

**Why:**
- REST for initial hydration, WS for incremental updates.

**Strengths:**
- Common and practical real-time dashboard pattern.

**Tradeoffs:**
- Requires careful event schema/versioning discipline.

---

## G. Risks / Weaknesses

### High-impact correctness issues

1. **Class update endpoint likely fails at runtime**
- `backend/api/classes.py` calls `class_manager.update_class(...)`.
- `backend/services/class_manager.py` has no `update_class` method.
- Expected impact: `PUT /api/classes/{name}` -> runtime `AttributeError` (500).

2. **WebSocket endpoint likely calls broadcast with wrong signature**
- `backend/api/socket.py` uses `await ws_manager.broadcast("message", {"data": data})`.
- `WebSocketManager.broadcast` expects one `payload: dict` (`backend/services/socket_manager.py`).
- Impact: client-to-server messages on `/ws` likely error.

3. **Class API error handling mismatch**
- `ClassManager.create_class/delete_class` raise `ValueError` (`backend/services/class_manager.py`).
- API layer often expects boolean/None patterns, not caught ValueError (`backend/api/classes.py`).
- Impact: duplicate create/delete-not-found may return 500, not clean 4xx.

### Medium-impact engineering risks

4. **Type mismatch in frontend group API contract**
- `frontend/src/services/groupApi.ts` types `getGroupTopics` as `string[]`.
- Backend returns object `{id, topics}` (`backend/api/groups.py`).
- `frontend/src/store/useGroupStore.ts` consumes `data.topics`.
- Impact: strict TypeScript build risk and contract drift.

5. **Duplicate comparison mutates arrays during sort**
- `topics.sort()` used directly inside equality checks in `useDuplicateStore.ts` and `DupeList.tsx`.
- In-place sort mutates original arrays in store objects.
- Impact: subtle state mutation bugs.

6. **Frontend duplicate subscribe call path**
- `SubscribeInput` calls `subscribeTopic(topic)` and then `addTopic(topic)`; `addTopic` itself calls API again (`useMqttStore.ts`).
- Impact: duplicate API calls, potential redundant backend operations.

7. **Broadcast robustness**
- `WebSocketManager.broadcast` sends sequentially and does not isolate/remove broken connections on send failure.
- Impact: one bad socket may disrupt event fan-out.

8. **Hardcoded service URLs in frontend**
- Multiple modules hardcode `http://localhost:8000` and `ws://localhost:8000`.
- Impact: deployment/environment inflexibility.

### Scalability / reliability / maintainability concerns

9. Metadata stores are local JSON (`backend/services/store/*.py`): no locking/versioning/conflict handling.
10. Embedding and duplicate checks run in process; heavy model + async tasks may compete with API responsiveness under high traffic.
11. CORS is fully open (`allow_origins=["*"]` in `backend/main.py`) and no auth is evident.
12. Observability is mostly `print`-based (no structured logging/metrics/tracing).

### Not evident from codebase

- Authentication/authorization framework: **not evident from codebase**.
- Container/deployment manifests (Dockerfile, docker-compose, k8s, IaC): **not evident from codebase**.
- Background job queue infrastructure (Celery/RQ/Kafka workers): **not evident from codebase**.

---

## H. Defense Preparation (Subsystem by Subsystem)

### 1) Ingestion + Persistence subsystem

**What to say:**
- "I use an ordered MQTT handler pipeline: topic discovery/semantic triggers first, then Influx persistence, then WebSocket broadcast. This keeps concerns isolated while preserving deterministic processing order."

**Why design is reasonable:**
- Single message fan-out to independent concerns with clear extension points.

**Likely questions and strong answers:**
- Q: "Why not write directly in one handler?"
- A: "The chain makes behavior composable and testable; each handler has one responsibility."
- Q: "How do you prevent ignored topics from polluting storage?"
- A: "`TopicHandler` short-circuits the pipeline when topic is in `ignored_topic_store`."

### 2) Semantic analysis subsystem

**What to say:**
- "For duplicates I combine semantic cosine similarity with a correlation score over recent numeric points, so matching considers both naming semantics and signal behavior."

**Why reasonable:**
- Better than string matching in IoT naming chaos.

**Likely questions and answers:**
- Q: "Why hybrid score?"
- A: "Cosine handles metadata semantics; correlation validates behavior similarity. Weighting increases with point count."
- Q: "What if not enough history exists?"
- A: "It falls back to embedding cosine when points are below `MIN_POINTS`."

### 3) API + frontend state subsystem

**What to say:**
- "I separate initial snapshot loading (REST) from live deltas (WebSocket). Zustand stores persist user-facing state and reconcile incoming event types by domain."

**Why reasonable:**
- Predictable startup + efficient real-time updates.

**Likely questions and answers:**
- Q: "How do you avoid full refresh polling?"
- A: "WS events (`mqtt_message`, `topic`, `duplicate`, `group`) incrementally update stores after bootstrap."
- Q: "How are charts updated?"
- A: "Baseline points come from `/timeseries`; live MQTT points append into chart datasets in `RealtimeGraph`."

### 4) Metadata modeling subsystem

**What to say:**
- "Telemetry durability is in InfluxDB; mutable metadata is kept in JSON stores for lightweight iteration and transparency."

**Why reasonable:**
- Good for prototype/research velocity.

**Likely questions and answers:**
- Q: "Is JSON store production-safe?"
- A: "For prototype scale yes; for multi-instance production I’d migrate class/dupe/tag/topic metadata to a transactional DB."

---

## I. Short SWE Defense Script

"This project is a modular real-time IoT intelligence platform. The backend is a FastAPI process that starts MQTT and InfluxDB services, then routes each MQTT message through a handler pipeline: topic detection and semantic processing, timeseries persistence, and real-time WebSocket broadcasting. I separated storage intentionally: InfluxDB for high-volume telemetry and JSON stores for mutable metadata like duplicate decisions, tag groups, and saved classes.

On top of ingestion, I added semantic intelligence. New topics are embedded with SentenceTransformer; duplicate detection uses a hybrid score that combines embedding cosine with time-series correlation, so we catch both naming and behavioral similarity. Grouping is tag-embedding based and streamed to the UI.

The frontend uses React + Zustand with a snapshot-plus-stream model: REST endpoints load baseline state, WebSocket events apply live deltas. This architecture made development fast and explainable, with clear service boundaries. Tradeoff-wise, I prioritized research velocity over production hardening; known next steps are replacing local JSON metadata stores with durable shared storage, tightening API error handling, and adding stronger test coverage and deployment artifacts." 

---

## Folder Responsibility Map

- `backend/api`: FastAPI route handlers (topic, data, duplicates, classes, groups, health, websocket)
- `backend/services`: core business logic and integration managers (mqtt, influx, embedding, duplicates, grouping, stores)
- `backend/models`: Pydantic request/response and domain models
- `backend/utils`: math helper(s) used by semantic clustering
- `backend/data`: persisted runtime JSON metadata/state
- `frontend/src/components`: UI composition by feature
- `frontend/src/store`: Zustand state containers and domain actions
- `frontend/src/services`: HTTP API client layer
- `frontend/src/hooks`: bootstrap and websocket integration hooks
- `test`: script-style validation tools/simulators (not formal unit test suite)

---

## External Dependencies (Important)

### Backend
- Web/API: FastAPI, Uvicorn, Pydantic
- Messaging: paho-mqtt
- Time-series DB: influxdb-client
- ML/embeddings: sentence-transformers, transformers, torch, numpy, scipy, scikit-learn
- Config: python-dotenv

Source: `backend/requirements.txt`, `backend/config.py`.

### Frontend
- React 19, Vite, TypeScript
- Zustand for state management
- Axios for HTTP
- Chart.js + react-chartjs-2 + date-fns adapter

Source: `frontend/package.json`.

---

## Config / Deployment Artifact Inventory

### Present
- Runtime env template: `backend/.env.example`
- Runtime config loader/defaults: `backend/config.py`
- Frontend build config: `frontend/vite.config.ts`
- TypeScript compiler configs: `frontend/tsconfig*.json`

### Not evident from codebase
- Dockerfile / docker-compose files
- Kubernetes/IaC manifests
- CI/CD pipeline definitions
- Custom OpenAPI/YAML contract files

---

## Testing Strategy and Coverage Gaps

### Current strategy (fact)
- Test scripts are executable Python programs, mostly scenario/simulation based:
  - `test/test_duplicate.py`
  - `test/test_similarity.py`
  - `test/test_tag_group.py`
  - `test/test_piblisher.py`
  - utility MQTT pub/sub scripts: `test/pub.py`, `test/sub.py`

### Coverage gaps (inference from code layout)
- No pytest-style assertion-based automated unit/integration suite is evident.
- No API contract tests for REST status/error behavior.
- No frontend unit/component tests.
- No WebSocket resilience/reconnect/load tests.
- No explicit performance tests for embedding latency or high message throughput.

---

## Final Owner-Defense Framing

If asked, "Can you explain how your system works and why this design?":

- Emphasize the **pipeline architecture** and **separation of concerns**.
- Explain **hybrid semantic + signal duplicate detection** as a deliberate engineering decision.
- Be explicit about **prototype vs production tradeoffs**:
  - current strengths: clarity, modularity, real-time behavior, feature completeness
  - next hardening steps: metadata DB migration, API bug fixes, stronger tests, deployment automation.
