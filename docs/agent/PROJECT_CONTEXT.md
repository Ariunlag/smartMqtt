# Smart-MQTT++ Project Context

Smart-MQTT++ is an AI-assisted IoT telemetry management platform for schema-flexible IoT data streams.

The original Smart-MQTT system was developed as a research prototype for MQTT-based real-time ingestion, InfluxDB time-series storage, semantic duplicate detection, tag-based topic grouping, user-defined classes, and WebSocket-based visualization.

The goal of Smart-MQTT++ is to extend the prototype into a deployable research and engineering platform.

Core goals:
- Ingest real-time MQTT telemetry.
- Store numeric sensor data in InfluxDB.
- Detect duplicate or semantically similar telemetry streams.
- Recommend topic classes using embedding similarity.
- Support schema-flexible JSON payloads.
- Provide real-time visualization through a React dashboard.
- Add deployment support through Docker.
- Add benchmark scripts and measurable performance results.
- Support future multi-source ingestion such as multiple MQTT brokers, HTTP telemetry APIs, and dataset replay.

Current technology stack:
- Backend: Python, FastAPI, Paho MQTT, InfluxDB client, Sentence Transformers.
- Frontend: React, TypeScript, Vite, Zustand, Chart.js.
- Storage: InfluxDB for time-series data; local JSON metadata stores in the current prototype.
- Future storage: PostgreSQL or SQLite for metadata; Qdrant or FAISS for embeddings.

Important principle:
Do not rewrite the entire project. Improve it incrementally while preserving the working prototype.
