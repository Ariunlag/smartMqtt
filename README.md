# SmartCity Realtime IoT Hub

## 1. Overview
The **SmartCity Realtime IoT Hub** is a modular IoT platform built with **FastAPI** and **React** for real-time telemetry ingestion, semantic analysis, and visualization.

It ingests MQTT messages, stores data in InfluxDB, embeds topic names and tags using `BAAI/bge-small-en-v1.5`, detects duplicates, groups related topics by semantic similarity, and allows users to create and manage **Saved Classes**.  
All system events are synchronized with the UI in real time using **WebSockets**.

---

## 2. Main Features

### 2.1 Real-Time Telemetry and Visualization
- **Subscribes** to multiple MQTT topics for continuous telemetry ingestion.
- **Stores** all sensor readings in InfluxDB for real-time and historical analysis.
- **Displays** live charts and time-series graphs using React and Chart.js.
- **Synchronizes** all updates with the UI instantly through WebSocket connections.

### 2.2 User-Defined Classes
- Users define **Classes** — named collections of related topics.
- Classes persist as metadata in **JSON files**, can be modified or deleted.
- Selecting a class loads all associated topics and data.

### 2.3 Duplicate Detection
- Each topic is semantically embedded with `BAAI/bge-small-en-v1.5`.
- System compares embeddings to find duplicates above a similarity threshold (`ID_THRESH`).
- Duplicate candidates stored in JSON and broadcast to frontend.
- Users approve/reject detected duplicates directly in the UI.

### 2.4 Tag-Based Semantic Grouping
- Tag values (e.g., room, floor) are **embedded and compared semantically**.
- Topics with similar tag embeddings are automatically grouped.
- Group updates are pushed to the frontend via WebSockets for visualization.

---

## 3. Screenshots

- **System Dashboard:**  
  ![System Dashboard](images/dashboard.png)
- **Duplicate Manager:**  
  ![Duplicate Manager](images/duplicate_manager.png)
- **Tag Grouping Panel:**  
  ![Tag Grouping](images/tag_grouping.png)
- **Saved Classes Panel:**  
  ![Saved Classes](images/classes_panel.png)

---

## 4. Data Handling

The system **separates telemetry data from metadata**.

### 4.1 Time-Series Data (InfluxDB)
- **All numeric and timestamped sensor data stored in InfluxDB**
- Supports fast range queries, aggregations, and historical visualization.

### 4.2 Metadata (JSON Storage)

Maintains topic-level semantic information and user configurations:

| File Name              | Description                    |
|------------------------|--------------------------------|
| `embedding_store.json` | Topic and tag embeddings       |
| `duplicate_store.json` | Detected duplicates            |
| `tagset_store.json`    | Tag-based groups               |
| `class_store.json`     | User-defined saved classes     |

Database-ready, can migrate to PostgreSQL/MongoDB without changing app logic.

---

## 5. Configuration

All parameters are defined in `config.py`:

MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
INFLUX_URL = "http://localhost:8086"
INFLUX_BUCKET = "smartcity"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DEVICE = "cpu"
ID_THRESH = 0.9 # Duplicate detection threshold
GROUP_TAG_THRESH = 0.85 # Tag grouping threshold

text

---

## Embedding Model

[Embedding] Loading model: BAAI/bge-small-en-v1.5 on device=cpu

text

Generates normalized embeddings for both topics and tags for unified semantic comparison.

---

## 6. System Workflow

MQTT → TopicHandler → EmbeddingManager
→ DupeManager ─→ WebSocket (duplicate)
→ GroupManager ─→ WebSocket (group)

text
A new topic arrives via MQTT:
- TopicHandler registers the topic and triggers embedding.
- EmbeddingManager generates embeddings for topic and tags.
- DupeManager checks for duplicates and notifies the frontend.
- GroupManager identifies tag-based semantic relationships.
- All updates are broadcast live to the UI.

---

## 7. Backend Architecture

services/
│
├── mqtt/ # MQTT client and message handling
├── embedding_manager.py # Topic/tag embedding logic
├── dupe_manager.py # Duplicate detection using embeddings
├── groups_manager.py # Tag-based semantic grouping
├── class_manager.py # Manages user-defined classes
├── topic_manager.py # Registers and tracks topics
├── socket_manager.py # WebSocket communication
└── influx_manager.py # Interfaces with InfluxDB

text

---

## 8. Frontend Architecture

frontend/
src/
components/
mqtt/ # MQTT topic view
duplicates/ # Duplicate detection UI
groups/ # Tag-based grouping panel
classes/ # Class management interface
graphs/ # Real-time/historical graphs
store/ # Zustand stores
hooks/ # WebSocket/API hooks
services/ # Axios API handlers
App.tsx # Root component
main.tsx # Entry point

text

---

## 9. Installation and Setup

### Backend Setup
pip install -r requirements.txt
uvicorn main:app --reload

text

### Frontend Setup
npm install
npm run dev

text

Access dashboard: [http://localhost:5173](http://localhost:5173/)

---

## 10. How to Run

1. **Start InfluxDB** and configure your bucket and token.
2. **Run backend:**  
   `uvicorn main:app --reload`
3. **Run frontend:**  
   `npm run dev`
4. **Publish MQTT data** (client/test script).
5. **Open the web UI** to see live updates, duplicates, groups.

---

## 11. Summary

The **SmartCity Realtime IoT Hub** integrates real-time data ingestion with semantic understanding.

- Ingests and visualizes MQTT telemetry
- Uses BAAI/bge-small-en-v1.5 for embeddings
- Detects duplicate topics
- Groups related topics
- Stores telemetry in InfluxDB, metadata in JSON
- Extensible for future scaling with databases and analytics

---