# SmartCity Realtime IoT Hub - Comprehensive Architecture Overview

## 1. Project Purpose & Functionality

**SmartCity Realtime IoT Hub** is an intelligent IoT platform designed for real-time telemetry ingestion, semantic analysis, and live visualization. The system processes thousands of MQTT messages per second, detects semantic duplicates, groups topics intelligently, and provides a responsive dashboard for monitoring and management.

### Core Capabilities:
- **Real-Time MQTT Ingestion**: Subscribes to MQTT topics and processes messages instantly
- **Time-Series Storage**: Writes numeric sensor readings to InfluxDB
- **Semantic Intelligence**: Uses embeddings to detect duplicate topics and group related data
- **User-Defined Classes**: Create named groups of topics for custom monitoring scenarios
- **Live Dashboard**: React-based UI with real-time updates via WebSockets
- **Interactive Management**: Approve/reject duplicates, manage groups, save custom classes

---

## 2. Technology Stack & Frameworks

### Backend Stack
| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | FastAPI | 0.117.1 |
| **MQTT Client** | Paho MQTT | 2.1.0 |
| **Database** | InfluxDB Client | 1.49.0 |
| **Embeddings** | Sentence Transformers | 5.1.1 |
| **ML Framework** | PyTorch | 2.8.0 |
| **Server** | Uvicorn | 0.37.0 |
| **Validation** | Pydantic | 2.11.9 |
| **Config** | Python-dotenv | 1.1.1 |
| **Data Processing** | NumPy, Scikit-learn | 2.3.3, 1.7.2 |

### Frontend Stack
| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | React | 19.1.1 |
| **Build Tool** | Vite | 7.1.7 |
| **Language** | TypeScript | 5.8.3 |
| **State Management** | Zustand | 5.0.8 |
| **HTTP Client** | Axios | 1.12.2 |
| **Charting** | Chart.js | 4.5.0 |
| **Linting** | ESLint | 9.36.0 |

### Key Dependencies Summary
- **ML/Embeddings**: Transformers, Tokenizers, Safetensors, HuggingFace Hub
- **Data Science**: NumPy, SciPy, Scikit-learn, Scipy
- **Networking**: Requests, AnyIO, Certifi
- **Utilities**: Six, TqdM, PyYAML, Regex

---

## 3. Architecture Patterns & High-Level Design

### 3.1 Overall System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      External IoT Systems                        │
│                   (MQTT Brokers & Sensors)                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ MQTT Messages (JSON)
                         ▼
        ┌────────────────────────────────────┐
        │     MQTT Handler Pipeline          │
        │  ┌──────────────────────────────┐  │
        │  │ 1. TopicHandler              │  │
        │  │    (Detects new topics)      │  │
        │  └──────────────┬───────────────┘  │
        │                 │                  │
        │  ┌──────────────▼───────────────┐  │
        │  │ 2. InfluxHandler             │  │
        │  │    (Writes to DB)            │  │
        │  └──────────────┬───────────────┘  │
        │                 │                  │
        │  ┌──────────────▼───────────────┐  │
        │  │ 3. Broadcaster               │  │
        │  │    (WebSocket broadcast)     │  │
        │  └──────────────┬───────────────┘  │
        │                 │                  │
        └─────────────────┼──────────────────┘
                          │
        ┌─────────────────┼──────────────────────────────┐
        │                 │                              │
        │       ┌─────────▼──────────┐                   │
        │       │   ASYNC TASKS      │                   │
        │       │ (Embedding, Dupe   │                   │
        │       │  Detection)        │                   │
        │       └────────────────────┘                   │
        │                                                │
        │  ┌─────────────────────────────────────────┐  │
        │  │     Backend Services & Managers         │  │
        │  │                                         │  │
        │  │  • EmbeddingManager                    │  │
        │  │  • DupeManager                         │  │
        │  │  • GroupManager                        │  │
        │  │  • TopicManager                        │  │
        │  │  • ClassManager                        │  │
        │  │  • InfluxManager                       │  │
        │  │  • QueryManager                        │  │
        │  │  • TagManager                          │  │
        │  │  • SocketManager (WebSocket)           │  │
        │  └─────────────────────────────────────────┘  │
        │                                                │
        │  ┌─────────────────────────────────────────┐  │
        │  │     Data Persistence Layer              │  │
        │  │                                         │  │
        │  │  JSON Stores:                          │  │
        │  │  • topic_store.json                    │  │
        │  │  • detected_topic_store.json           │  │
        │  │  • dupe_store.json                     │  │
        │  │  • tagset_store.json                   │  │
        │  │  • class_store.json                    │  │
        │  │  • topic_embedding_store.json          │  │
        │  │                                         │  │
        │  │  InfluxDB: Time-series measurements    │  │
        │  └─────────────────────────────────────────┘  │
        │                                                │
        └────────────────────────────────────────────────┘
                         │
                         │ REST API + WebSocket
                         ▼
        ┌────────────────────────────────────────────────┐
        │          React Frontend (Vite)                 │
        │                                                │
        │  ┌──────────────────────────────────────────┐ │
        │  │  Zustand Stores                          │ │
        │  │  • useMqttStore                          │ │
        │  │  • useInfluxStore                        │ │
        │  │  • useDuplicateStore                     │ │
        │  │  • useGroupStore                         │ │
        │  └──────────────────────────────────────────┘ │
        │                                                │
        │  ┌──────────────────────────────────────────┐ │
        │  │  Components                              │ │
        │  │  • MqttManager                           │ │
        │  │  • DuplicateManager                      │ │
        │  │  • ClassBuilder                          │ │
        │  │  • SavedClasses                          │ │
        │  │  • GroupManager                          │ │
        │  │  • Charts & Graphs                       │ │
        │  └──────────────────────────────────────────┘ │
        │                                                │
        └────────────────────────────────────────────────┘
```

### 3.2 Message Processing Pipeline

```
MQTT Message Arrives
        │
        ▼
┌──────────────────────────────┐
│  TopicHandler.handle_message │
│  - Parse JSON payload        │
│  - Check if topic ignored    │
│  - Detect new topics         │
└──────────┬───────────────────┘
           │
           ├─ NEW TOPIC DETECTED
           │  └─ trigger: EmbeddingManager.process_new_topic()
           │     ├─ embed_flattened_topic (topic + tags)
           │     ├─ embed_tags (individual tag values)
           │     └─ trigger: DupeManager.check_new_topic()
           │        └─ Delayed async check (3x with 60s delay)
           │           - Compare embeddings via cosine similarity
           │           - If score >= ID_THRESH → broadcast duplicate
           │
           ▼
┌──────────────────────────────┐
│  InfluxHandler.handle_message│
│  - Write fields to InfluxDB  │
│  - Non-blocking async write  │
└──────────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  Broadcaster.handle_message  │
│  - Format for WebSocket      │
│  - Send to all clients       │
└──────────────────────────────┘
           │
           ▼
Frontend Receives Update (WebSocket)
        │
        ▼
Store Update (Zustand)
        │
        ▼
React Re-render
```

### 3.3 Semantic Duplicate Detection

```
New Topic Detected
        │
        ▼
Flatten: "topic_name + tag_values" → sentence
        │
        ▼
Embed via BAAI/bge-small-en-v1.5 → vector
        │
        ▼
Store in topic_embedding_store.json
        │
        ▼
Schedule 3 Delayed Checks (every 60s)
        │
        ├─ For each existing topic embedding:
        │  └─ hybrid_score() = cosine_similarity(new_vec, existing_vec)
        │
        ├─ If score >= 0.90:
        │  ├─ Add to dupe_store.json (PENDING)
        │  └─ Broadcast via WebSocket
        │
        └─ If no duplicates found after 3 checks:
           └─ Topic stands alone
```

### 3.4 Tag-Based Semantic Grouping

```
New Topic Embeddings Received
        │
        ▼
EmbeddingManager.embed_tags()
        │
        ├─ For each tag value:
        │  ├─ Embed individually
        │  └─ Call TagManager.process_tag()
        │
        ▼
GroupManager.update_for_topic()
        │
        ├─ For each tag embedding:
        │  └─ tagset_store.find_or_create_set()
        │     ├─ Compare against existing sets
        │     ├─ If cosine_sim >= 0.85 → add to set
        │     └─ If no match → create new set
        │
        ├─ Collect all sets with ≥2 topics
        │
        └─ Broadcast all valid sets via WebSocket
```

---

## 4. Key Services & Modules

### 4.1 Backend Service Layer Architecture

```
services/
├── service_manager.py
│   └── Lifecycle management (startup/shutdown)
│       ├── Connects MQTT & InfluxDB clients
│       ├── Registers MQTT handlers
│       └── Performs health checks
│
├── topic_manager.py
│   └── MQTT topic subscription management
│       ├── subscribe() / unsubscribe()
│       ├── get_subscribed_topics()
│       └── resubscribe_all() on reconnect
│
├── embedding_manager.py
│   └── Semantic embedding pipeline
│       ├── embed_flattened_topic() (topic + tags)
│       ├── embed_tags() (individual values)
│       └── process_new_topic() (full pipeline)
│
├── dupe_manager.py
│   └── Duplicate detection orchestration
│       ├── check_new_topic() (delayed async)
│       ├── add_candidate() (store record)
│       ├── confirm_duplicate() (unsubscribe)
│       ├── keep_both() (mark as not duplicate)
│       └── list_pending() (fetch pending pairs)
│
├── groups_manager.py
│   └── Tag-based semantic grouping
│       ├── update_for_topic()
│       ├── list_sets()
│       └── get_topics_for_set()
│
├── class_manager.py
│   └── User-defined topic classes
│       ├── create_class()
│       ├── update_class()
│       ├── delete_class()
│       └── list_classes()
│
├── influx_manager.py
│   └── High-level InfluxDB interface
│       └── write_message() (async write)
│
├── query_manager.py
│   └── InfluxDB Flux query builder
│       ├── list_measurements()
│       ├── get_timeseries()
│       └── get_recent_messages()
│
├── socket_manager.py
│   └── WebSocket broadcast manager
│       ├── connect()
│       ├── disconnect()
│       └── broadcast()
│
├── tag_manager.py
│   └── Tag parsing & normalization
│       └── process_tag()
│
└── mqtt/
    ├── client.py
    │   └── Paho MQTT wrapper (singleton)
    │       ├── connect() / disconnect()
    │       ├── subscribe() / unsubscribe()
    │       ├── register_handler()
    │       └── Health check
    │
    ├── handler_setup.py
    │   └── Register 3-handler pipeline:
    │       ├── TopicHandler (detection)
    │       ├── InfluxHandler (persistence)
    │       └── Broadcaster (WebSocket)
    │
    ├── base_handler.py
    │   └── Abstract handler interface
    │
    └── handlers/
        ├── topic_handler.py
        ├── influx_handler.py
        └── ws_handler.py
```

### 4.2 Data Persistence Layer

**JSON Stores** (in `backend/data/`):
| File | Purpose | Schema |
|------|---------|--------|
| `topic_store.json` | Active subscriptions | `["topic1", "topic2", ...]` |
| `detected_topic_store.json` | All detected topics | `["topic1", "topic2", ...]` |
| `dupe_store.json` | Duplicate pairs | `[{topics: [...], score: 0.95, status: "PENDING"}, ...]` |
| `tagset_store.json` | Tag-based groups | `[{id: "set1", tags: [...], topics: [...], ...}, ...]` |
| `class_store.json` | User-defined classes | `[{name: "BuildingA_HVAC", topics: [...]}, ...]` |
| `topic_embedding_store.json` | Topic embeddings | `[{topic: "...", embedding: [...], tags: {...}}, ...]` |

**InfluxDB**:
- **Bucket**: `smartHub` (configurable)
- **Org**: `Test1` (configurable)
- **Measurement**: Topic name
- **Tags**: Extracted from MQTT message tags
- **Fields**: Numeric values from MQTT message fields
- **Retention**: Configurable per organization

### 4.3 Service Initialization Flow

```
FastAPI app.on_event("startup")
        │
        ▼
ServiceManager.startup()
        │
        ├─ register_mqtt_handlers()
        │  └─ TopicHandler + InfluxHandler + Broadcaster
        │
        ├─ For each service (MQTT, InfluxDB):
        │  ├─ set_loop() (bind asyncio loop)
        │  └─ connect() (establish connection)
        │
        ├─ topic_manager.resubscribe_all()
        │
        └─ Health check all services
           └─ Raise RuntimeError if any fail
```

---

## 5. API Endpoints

### 5.1 Topics API (`/api/topics`)
```
GET  /api/topics
     → TopicListResponse { topics: ["topic1", "topic2", ...] }
     └─ Returns all subscribed MQTT topics

POST /api/subscribe
     Request: { topic: "device/+/temperature" }
     Response: { status: "subscribed", topic: "..." }
     └─ Subscribe to new MQTT topic

POST /api/unsubscribe
     Request: { topic: "device/+/temperature" }
     Response: { status: "unsubscribed", topic: "..." }
     └─ Unsubscribe and remove from store
```

### 5.2 Data API (`/api/data`)
```
GET  /api/measurements
     → { topics: ["measurement1", "measurement2", ...] }
     └─ List all measurements in InfluxDB

GET  /api/timeseries?names[]=measurement1&names[]=measurement2
     → [
         {
           measurement: "temperature",
           points: [
             { timestamp: "2024-01-01T00:00:00", value: 22.5 },
             { timestamp: "2024-01-01T00:01:00", value: 22.6 }
           ]
         }
       ]
     └─ Get timeseries data (default last 30 days)

GET  /api/messages?limit=200
     → { messages: [...] }
     └─ Get last N messages from all topics
```

### 5.3 Duplicates API (`/api/duplicates`)
```
GET  /api/duplicates
     → {
         duplicates: [
           {
             topics: ["topic_a", "topic_b"],
             score: 0.93,
             status: "PENDING"
           }
         ]
       }
     └─ List all pending duplicate pairs

POST /api/duplicate-confirm
     Request: {
       topics: ["topic_a", "topic_b"],
       action: "UNSUBSCRIBE" | "KEEP_BOTH",
       target?: "topic_b"
     }
     Response: DupeRecord
     └─ Confirm or reject a duplicate pair
```

### 5.4 Classes API (`/api/classes`)
```
GET    /api/classes/
       → { classes: [{name: "BuildingA_HVAC", topics: [...]}, ...] }
       └─ List all saved classes

POST   /api/classes/
       Request: { name: "BuildingA_HVAC", topics: ["topic1", "topic2"] }
       Response: ClassRecord
       └─ Create new class

PUT    /api/classes/{name}
       Request: { topics: ["new_topic1", "new_topic2"] }
       Response: ClassRecord
       └─ Update class topics

DELETE /api/classes/{name}
       Response: { status: "deleted", name: "BuildingA_HVAC" }
       └─ Delete class
```

### 5.5 Groups API (`/api/groups`)
```
GET    /api/groups
       → {
           sets: [
             { id: "set_1", tags: ["HVAC", "Building_A"] },
             { id: "set_2", tags: ["Sensor", "Floor_3"] }
           ]
         }
       └─ List all tag groups with ≥2 topics

GET    /api/groups/{set_id}/topics
       → {
           id: "set_1",
           topics: ["topic1", "topic2", "topic3"]
         }
       └─ Get topics belonging to a group
```

### 5.6 Health API (`/api/health`)
```
GET    /api/health
       → {
           MQTTClient: true,
           InfluxClient: true,
           ...
         }
       └─ Check health of all backend services
```

### 5.7 WebSocket (`/ws`)
```
WebSocket /ws

Incoming (from client):
  Any text data → broadcast to all connected clients

Outgoing (from backend):
  {
    event_type: "mqtt_message" | "topic" | "duplicate" | "group",
    data: {...}
  }

Event Types:
  - "mqtt_message": New MQTT message received
  - "topic": New topic detected
  - "duplicate": New duplicate pair found
  - "group": Tag groups updated
```

---

## 6. Data Models

### 6.1 Core Request/Response Models

```python
# Topics
TopicListResponse:
  - topics: List[str]

TopicSubscribeRequest:
  - topic: str

TopicResponse:
  - status: str ("subscribed" | "unsubscribed")
  - topic: str

# Measurements (Time-Series)
MeasurementPoint:
  - timestamp: datetime
  - value: float

MeasurementSeriesResponse:
  - measurement: str
  - points: List[MeasurementPoint]

# Duplicates
DupeStatus: Enum("PENDING", "CONFIRMED_DUPLICATE", "NOT_DUPLICATE")
DupeAction: Enum("KEEP_BOTH", "UNSUBSCRIBE")

DupeRecord:
  - topics: List[str] (exactly 2)
  - score: float (0.0-1.0)
  - status: DupeStatus

DupeListResponse:
  - duplicates: List[DupeRecord]

ConfirmDupeRequest:
  - topics: List[str] (exactly 2)
  - action: DupeAction
  - target?: str (optional target to unsubscribe)

# Classes (User Groups)
ClassRecord:
  - name: str
  - topics: List[str]

ClassListResponse:
  - classes: List[ClassRecord]

CreateClassRequest:
  - name: str
  - topics: List[str]

UpdateClassRequest:
  - topics: List[str]

# Groups (Tag-based)
TagSetRecord:
  - id: str
  - tags: List[str]

GroupListResponse:
  - sets: List[TagSetRecord]
```

### 6.2 Internal Message Models

```python
# MQTT Message (from broker)
MQTTMessage:
  - topic: str
  - tags: dict
  - fields: dict
  - timestamp: datetime

# Influx Point (for storage)
InfluxPoint:
  - measurement: str
  - tags: Dict[str, str]
  - fields: Dict[str, Any]
  - timestamp: datetime
```

### 6.3 Store Data Structures

```json
// topic_embedding_store.json
[
  {
    "topic": "sensors/building_a/hvac_temp",
    "embedding": [0.1234, -0.5678, ...],  // 384 dims from BAAI/bge-small-en-v1.5
    "tags": {"location": "building_a", "type": "hvac"}
  }
]

// dupe_store.json
[
  {
    "topics": ["sensors/hvac_temperature", "devices/hvac_temp"],
    "score": 0.945,
    "status": "PENDING"
  }
]

// tagset_store.json
[
  {
    "id": "tag_set_1",
    "tags": ["HVAC", "Temperature"],
    "topics": ["topic1", "topic2", "topic3"],
    "tag_embeddings": [[...], [...]]
  }
]

// class_store.json
[
  {
    "name": "BuildingA_HVAC",
    "topics": ["sensors/building_a/hvac_temp", "sensors/building_a/hvac_humidity"]
  }
]
```

---

## 7. External Integrations

### 7.1 MQTT Integration

**Configuration** (from `.env`):
```
MQTT_BROKER=test.mosquitto.org
MQTT_PORT=1883
```

**Client**: Paho MQTT (async callback-based)

**Message Format** (expected JSON payload):
```json
{
  "fields": {
    "temperature": 22.5,
    "humidity": 65
  },
  "tags": {
    "location": "room_101",
    "building": "A"
  },
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

**Flow**:
1. Subscribe to topic patterns (e.g., `sensors/+/+`)
2. Receive JSON message
3. Parse and dispatch through handler pipeline
4. Store in InfluxDB, detect new topics, broadcast to WebSocket

### 7.2 InfluxDB Integration

**Configuration** (from `.env`):
```
INFLUX_URL=http://localhost:8086
INFLUX_BUCKET=smartHub
INFLUX_ORG=Test1
INFLUX_TOKEN=<your-token>
```

**Client**: InfluxDB v2 client (write_api + query_api)

**Write Operations**:
- Point-based writes via Paho write_api
- Auto-timestamps if not provided
- Non-blocking async operations
- Namespace: `{org}/{bucket}`

**Query Operations**:
- Flux query language
- List measurements
- Time-range queries (default last 30 days)
- Recent message fetching

### 7.3 Semantic Embeddings Integration

**Model**: `BAAI/bge-small-en-v1.5` (SentenceTransformers)

**Configuration** (from `.env`):
```
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DEVICE=cpu
```

**Capabilities**:
- Embedding dimension: 384
- Fine-tuned for semantic search
- Efficient for CPU/GPU inference
- Downloaded from HuggingFace Hub on first use

**Usage Points**:
1. Topic flattening: `"topic_name tag_value1 tag_value2"`
2. Individual tag embeddings
3. Cosine similarity computation for duplicates

**Performance Thresholds**:
```
ID_THRESH = 0.90        # Duplicate detection threshold
GROUP_TAG_THRESH = 0.85 # Semantic grouping threshold
```

---

## 8. Frontend Architecture

### 8.1 Component Structure

```
src/
├── App.tsx
│   └── Main entry point with feature layout
│
├── components/
│   ├── mqtt/
│   │   └── MqttManager.tsx (Subscribe/unsubscribe UI)
│   │
│   ├── duplicates/
│   │   ├── DuplicateManager.tsx (Main container)
│   │   ├── DupeGraph.tsx (Similarity visualization)
│   │   └── DupeList.tsx (Pending pairs list)
│   │
│   ├── classes/
│   │   ├── ClassBuilder.tsx (Create new classes)
│   │   ├── ClassNameInput.tsx
│   │   ├── MeasurementsList.tsx
│   │   └── SelectedMeasurements.tsx
│   │
│   ├── savedClasses/
│   │   └── SavedClasses.tsx (List & load classes)
│   │
│   ├── groups/
│   │   └── GroupManager.tsx (Tag groups visualization)
│   │
│   ├── graphs/
│   │   ├── GraphBox.tsx (Single chart container)
│   │   └── GraphGrid.tsx (Chart grid layout)
│   │
│   ├── layout/
│   │   └── Header/Footer components
│   │
│   └── ... (more component folders)
│
├── hooks/
│   ├── useBootstrap.ts (Initial data fetch)
│   │   ├── Health check
│   │   ├── Fetch topics, classes, duplicates
│   │   └── Fetch measurements
│   │
│   └── useWebSocket.ts (Real-time updates)
│       └─ Listen for WebSocket events and update stores
│
├── store/ (Zustand state management)
│   ├── useMqttStore.ts (Topics, messages)
│   ├── useInfluxStore.ts (Measurements, timeseries, classes)
│   ├── useDuplicateStore.ts (Duplicates)
│   └── useGroupStore.ts (Tag groups)
│
├── services/ (API clients)
│   ├── dataApi.ts (Measurements, timeseries, messages)
│   ├── duplicateApi.ts (List, confirm duplicates)
│   ├── groupApi.ts (List groups, get topics)
│   ├── influxApi.ts (Charts, class data)
│   ├── topicApi.ts (Subscribe, unsubscribe, list)
│   └── lineChartService.ts (Chart formatting)
│
├── types/
│   ├── api_models.ts (TypeScript interfaces for API responses)
│   └── mqtt.ts (MQTT message types)
│
├── assets/ (Images, styles)
├── App.tsx (Main component)
├── main.tsx (Entry point)
└── index.css (Global styles)
```

### 8.2 State Management (Zustand)

**Store Pattern**:
```typescript
create<StateInterface>()(
  persist(
    (set, get) => ({
      // State variables
      data: [],
      
      // Actions
      fetchData: async () => {
        // Call API
        // Update state with set()
      },
      
      addItem: (item) => {
        set(state => ({ data: [...state.data, item] }))
      }
    }),
    { name: "store-key" }  // Persisted to localStorage
  )
)
```

**Store 1: useMqttStore**
- State: `topics`, `messages`
- Actions: `getTopics()`, `loadMessages()`, `addTopic()`, `removeTopic()`, `addMessage()`
- Persistence: Yes (localStorage)

**Store 2: useInfluxStore**
- State: `measurements`, `selectedMeasurements`, `classes`, `selectedClass`, `timeseriesData`
- Actions: `getMeasurements()`, `addMeasurement()`, `saveClass()`, `deleteClass()`, `fetchTimeseriesData()`
- Persistence: Yes

**Store 3: useDuplicateStore**
- State: `duplicates`
- Actions: `getDuplicates()`, `addDuplicate()`, `confirmDuplicate()`, `keepBoth()`
- Persistence: Yes

**Store 4: useGroupStore**
- State: `groups`
- Actions: `fetchGroups()`, `setGroups()`, `getTopicsForSet()`
- Persistence: Yes

### 8.3 API Client Pattern

```typescript
// Example: topicApi.ts
export async function getSubscribedTopics(): Promise<TopicListResponse> {
  const response = await axios.get("http://localhost:8000/api/topics");
  return response.data;
}

export async function subscribeTopic(topic: string): Promise<TopicResponse> {
  const response = await axios.post("http://localhost:8000/api/subscribe", {
    topic
  });
  return response.data;
}
```

### 8.4 WebSocket Integration

```typescript
// useWebSocket.ts Hook
const ws = new WebSocket("ws://localhost:8000/ws");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  switch(msg.event_type) {
    case "mqtt_message":
      useMqttStore.getState().addMessage(msg.data);
      break;
    case "duplicate":
      useDuplicateStore.getState().addDuplicate(msg.data);
      break;
    case "group":
      useGroupStore.getState().setGroups(msg.data.sets);
      break;
  }
};
```

### 8.5 Bootstrap Sequence (useBootstrap)

```typescript
1. Health Check
   GET /api/health
   └─ Verify MQTTClient and InfluxClient are ready

2. Initial Data Load (parallel requests)
   ├─ GET /api/topics
   ├─ GET /api/duplicates
   ├─ GET /api/measurements
   ├─ GET /api/classes
   └─ GET /api/groups

3. Establish WebSocket Connection
   └─ useWebSocket hook activates

4. Set ready = true
   └─ UI renders with data
```

---

## 9. Configuration & Environment

### 9.1 Backend Configuration (config.py)

```python
Config Properties:
├── MQTT
│   ├── MQTT_BROKER (default: test.mosquitto.org)
│   └── MQTT_PORT (default: 1883)
│
├── InfluxDB
│   ├── INFLUX_URL (default: http://localhost:8086)
│   ├── INFLUX_BUCKET (default: smartHub)
│   ├── INFLUX_ORG (default: Test1)
│   └── INFLUX_TOKEN (required)
│
├── Embeddings
│   ├── EMBEDDING_MODEL (default: BAAI/bge-small-en-v1.5)
│   └── EMBEDDING_DEVICE (default: cpu | gpu)
│
├── Thresholds
│   ├── ID_THRESH (default: 0.90 | range: 0.0-1.0)
│   ├── MIN_POINTS (default: 10)
│   ├── DUPE_CHECK_DELAY (default: 60 seconds)
│   └── GROUP_TAG_THRESH (default: 0.85 | range: 0.0-1.0)
│
└── Data
    └── DATA_DIR (default: ./backend/data)
```

### 9.2 Frontend Configuration

Vite configuration (`vite.config.ts`):
- Dev server: `localhost:5173`
- Backend proxy: `localhost:8000`
- TypeScript strict mode enabled
- React fast refresh enabled

### 9.3 Environment File Template

```bash
# .env.example (for Git)

# MQTT Broker
MQTT_BROKER=test.mosquitto.org
MQTT_PORT=1883

# InfluxDB
INFLUX_URL=http://localhost:8086
INFLUX_BUCKET=smartHub
INFLUX_ORG=Test1
INFLUX_TOKEN=your_influx_token_here

# Embedding Model
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DEVICE=cpu

# Detection Thresholds
ID_THRESH=0.90
MIN_POINTS=10
DUPE_CHECK_DELAY=60
GROUP_TAG_THRESH=0.85

# Data Directory
DATA_DIR=./backend/data
```

---

## 10. Data Flow Diagrams

### 10.1 New MQTT Message Flow

```
MQTT Broker
    │ (publish to topic)
    ▼
MQTTClient.on_message()
    │ (parse JSON)
    ▼
MQTTMessage(topic, tags, fields, timestamp)
    │
    ├─ Dispatch to handler pipeline:
    │
    ├─► TopicHandler
    │   ├─ Check if topic in ignored_store → STOP if ignored
    │   ├─ Check if topic in detected_store
    │   └─ If NEW:
    │       ├─ Add to detected_store
    │       ├─ asyncio.create_task(embedding_manager.process_new_topic())
    │       │   ├─ embed_flattened_topic()
    │       │   ├─ embed_tags()
    │       │   └─ trigger dupe check (async)
    │       └─ Broadcast to WebSocket: {event_type: "topic", data: {measurement: topic}}
    │
    ├─► InfluxHandler
    │   └─ await influx_manager.write_message()
    │       └─ influx_client.write_point()
    │
    └─► Broadcaster
        └─ await ws_manager.broadcast({event_type: "mqtt_message", data: {...}})
            └─ For each WebSocket client:
                └─ Send JSON to client
                    └─ Frontend WebSocket.onmessage()
                        └─ Parse and dispatch to Zustand stores
                            └─ React re-renders
```

### 10.2 User Approves Duplicate Flow

```
User clicks "UNSUBSCRIBE" in UI
    │
    ▼
DuplicateManager component
    │
    ▼
duplicateApi.confirmDuplicate({topics: ["a", "b"], action: "UNSUBSCRIBE"})
    │
    ▼
POST /api/duplicate-confirm
    │
    ▼
dupe_manager.confirm_duplicate(topic_a, topic_b)
    ├─ Find pair in store
    ├─ Update status to "CONFIRMED_DUPLICATE"
    ├─ topic_manager.unsubscribe(topic_b)
    │   └─ mqtt_client.unsubscribe(topic_b)
    └─ Return updated record
        │
        ▼
Backend sends 200 response
    │
    ▼
Frontend updates useDuplicateStore
    │
    ▼
UI reflects change (pair removed from pending list)
```

### 10.3 User Creates Class Flow

```
User selects measurements in ClassBuilder
    │
    ▼
User clicks "Save as Class" with name
    │
    ▼
ClassBuilder component
    │
    ▼
influxApi.saveClass({name: "BuildingA_HVAC", topics: [...]})
    │
    ▼
POST /api/classes/
    │
    ▼
class_manager.create_class(name, topics)
    ├─ Check if name exists
    ├─ Add to class_store
    └─ Return ClassRecord
        │
        ▼
Backend sends 201 response
    │
    ▼
Frontend updates useInfluxStore.classes
    │
    ▼
SavedClasses component shows new class
```

---

## 11. Key Design Patterns

### 11.1 Singleton Pattern
- `service_manager` - Single orchestrator for all services
- `mqtt_client` - Single MQTT connection
- `influx_client` - Single InfluxDB connection
- `topic_manager` - Single topic subscription manager
- `dupe_manager` - Single duplicate detector
- `class_manager` - Single class store manager
- `ws_manager` - Single WebSocket broadcaster

### 11.2 Handler Pipeline Pattern
MQTT message processing uses a chain of handlers:
```
message → TopicHandler → InfluxHandler → Broadcaster
```
Each handler can:
- Process the message
- Return `True` to continue pipeline
- Return `False` to stop pipeline

### 11.3 Store Pattern (Backend)
JSON-based persistence layer:
- `BaseStore` (abstract) → `ListStore`, `DictStore` subclasses
- Automatic load() on init
- Automatic save() on modification
- Simple in-memory representation with file persistence

### 11.4 Async/Await Pattern
- FastAPI async request handlers
- Delayed async duplicate checking (background tasks)
- Non-blocking InfluxDB writes
- Thread pool executor for ML embeddings

### 11.5 Pub/Sub Pattern (Frontend)
Zustand stores act as observable subjects:
- Frontend components subscribe to store changes
- WebSocket events update stores
- Components auto-re-render on store changes

---

## 12. Key Performance Considerations

### 12.1 Embedding Performance
- Model: `BAAI/bge-small-en-v1.5` (384 dims)
- Device: CPU (configurable to GPU)
- Batching: Single topic → run in executor pool
- Caching: Embeddings stored in JSON for similarity checks

### 12.2 Duplicate Detection Optimization
- Delayed checking (configurable 60s delay, 3 retries)
- Only compares against existing topics
- Short-circuits on first match
- Broadcast only on match (not on every check)

### 12.3 InfluxDB Optimization
- Non-blocking async writes
- Point batching via Paho client
- Query limit on API responses
- No real-time subscription (polling instead)

### 12.4 WebSocket Broadcasting
- Single broadcast to all clients (not per-client loops)
- JSON serialization of payload
- No message queuing (fire-and-forget)

---

## 13. Deployment Architecture

### Local Development
```
Backend:
  uvicorn main.py --reload
  Listens on: http://127.0.0.1:8000

Frontend:
  npm run dev
  Served on: http://localhost:5173

Services:
  MQTT: test.mosquitto.org:1883 (public broker)
  InfluxDB: Local or remote instance
```

### Production Considerations
- Containerize backend (FastAPI + Uvicorn)
- Containerize frontend (Vite build output + Nginx)
- Use private MQTT broker
- Authenticate InfluxDB with token
- Persist data volumes
- Environment-based configuration
- Health check endpoints for orchestration

---

## Summary

**SmartCity Realtime IoT Hub** is a sophisticated real-time IoT platform that combines:

1. **Real-Time Ingestion**: MQTT → Paho client → Handler pipeline
2. **Intelligent Storage**: Dual-layer (JSON + InfluxDB)
3. **Semantic Analysis**: Sentence Transformers for embeddings & similarity
4. **Live Dashboard**: React + WebSocket for instant updates
5. **User Interaction**: Approve duplicates, create classes, manage groups

**Architecture Strengths**:
- Clean separation of concerns (services layer)
- Non-blocking async operations
- Real-time bidirectional communication
- Modular handler pipeline
- Persistent state with JSON stores
- Scalable embedding-based intelligence

**Technology Choices Rationale**:
- **FastAPI**: Modern, async-native, auto-documentation
- **Paho MQTT**: Lightweight, reliable MQTT client
- **InfluxDB**: Purpose-built for time-series data
- **Sentence Transformers**: Pre-trained semantic embeddings
- **React + Zustand**: Lightweight, reactive frontend state
- **WebSocket**: Low-latency bidirectional communication
