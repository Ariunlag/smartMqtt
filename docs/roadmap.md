# Smart-MQTT++ Roadmap

Smart-MQTT++ extends the original Smart-MQTT research prototype into a deployable AI-assisted telemetry management platform for schema-flexible IoT environments.

## Phase 1: Repository and Documentation Cleanup

Goals:
- Organize documentation.
- Standardize project naming.
- Add project context for coding agents.
- Prepare the repository for incremental development.

Deliverables:
- README cleanup.
- Architecture documentation.
- Engineering roadmap.
- Coding-agent instruction files.

## Phase 2: Local Deployment

Goals:
- Make the system runnable from a clean machine.
- Reduce manual setup.
- Support reproducible local demos.

Deliverables:
- Backend Dockerfile.
- Frontend Dockerfile.
- docker-compose.yml.
- Mosquitto container.
- InfluxDB container.
- `.env.example`.
- Local demo instructions.

## Phase 3: Multi-Source Ingestion

Goals:
- Extend the system beyond one MQTT broker.
- Support heterogeneous telemetry sources.

Deliverables:
- Multiple MQTT broker configuration.
- HTTP telemetry ingestion endpoint.
- Dataset replay adapter.
- Source metadata model.

## Phase 4: Benchmark and Evaluation

Goals:
- Produce measurable evidence for research publication and NIW support.

Deliverables:
- Synthetic MQTT publisher.
- Dataset replay benchmark.
- Throughput measurements.
- Latency measurements.
- Duplicate detection evaluation.
- Class recommendation evaluation.

## Phase 5: Persistence and Reliability

Goals:
- Replace prototype metadata storage with durable storage.
- Improve system robustness.

Deliverables:
- SQLite or PostgreSQL metadata store.
- Optional vector database integration.
- Retry logic.
- Structured logging.
- Error tracking.

## Phase 6: Security and External Deployment

Goals:
- Prepare the system for external demos and pilot deployments.

Deliverables:
- Restricted CORS.
- API authentication.
- MQTT username/password support.
- Payload validation.
- HTTPS deployment guide.
- Server deployment documentation.

## Long-Term Research Direction

The long-term research direction is explainable, pair-level telemetry class
recommendation for schema-flexible IoT streams.

Potential research contributions:
- Evaluation of hybrid embedding and temporal duplicate detection.
- Human-in-the-loop Saved Class recommendation.
- Multi-source telemetry normalization.
- Drift-aware stream grouping.
- Benchmarking pair-view contribution, coverage, and recommendation quality.
