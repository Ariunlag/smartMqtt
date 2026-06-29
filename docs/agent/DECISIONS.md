# Architecture Decisions

> Important engineering decisions for Smart-MQTT++.

---

## Decision 1: Keep MQTT as the Core Ingestion Protocol

Smart-MQTT++ will keep MQTT as the primary ingestion protocol because MQTT is widely used in IoT telemetry systems and matches the original research prototype.

Future versions may support HTTP APIs and dataset replay, but these should be implemented as source adapters instead of replacing MQTT.

---

## Decision 2: Normalize All Telemetry into One Internal Event Format

All sources should eventually be converted into a common internal telemetry event format.

**Suggested structure:**

```python
class NormalizedTelemetryEvent:
    source_type: str
    source_id: str
    stream_id: str
    topic_or_path: str
    timestamp: str
    value: float
    tags: dict
    raw_payload: dict
```

**Reason:** Duplicate detection, class recommendation, storage, and visualization should not depend on source-specific payload formats.

---

## Decision 3: Keep InfluxDB for Time-Series Data

InfluxDB remains the main storage engine for numeric telemetry points because the system is time-series oriented.

Metadata such as classes, duplicate decisions, topics, and feedback should eventually move from JSON files to a transactional database.

---

## Decision 4: Keep JSON Metadata Stores During Early Development

JSON stores are acceptable for the research prototype and local demo because they are simple and transparent.

They are not suitable for multi-instance production deployment. A future metadata database migration is required.

---

## Decision 5: Use Feature Branches for Each Module

Each major module should be developed in a separate feature branch.

**Examples:**

- `feature/docker-deployment`
- `feature/multi-broker`
- `feature/http-ingestion`
- `feature/benchmark`
- `feature/security-hardening`

**Reason:** This protects the working `dev-prod` branch and makes changes easier to review.

---

## Decision 6: Do Not Claim Production Readiness Too Early

Smart-MQTT++ should be described as a deployable research platform only after Docker deployment, basic security, benchmark scripts, and documentation are complete.
