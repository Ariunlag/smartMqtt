# Supported Data Sources

Smart-MQTT++ is designed to support schema-flexible telemetry from multiple sources.

## Current Source

### MQTT

MQTT is the current primary source.

Expected payload format:

```json
{
  "fields": {
    "temperature": 22.5
  },
  "tags": {
    "location": "room_101",
    "building": "A",
    "sensor_type": "temperature"
  },
  "timestamp": "2026-05-13T12:00:00Z"
}

The MQTT topic acts as the stream identifier.

Example topics:

building1/floor2/temperature
building1/floor2/humidity
building2/floor1/airquality
Planned Sources
Multiple MQTT Brokers

Smart-MQTT++ should support multiple MQTT brokers.

Each broker should have:

broker_id
host
port
username/password where needed
topic filters
source metadata
HTTP Telemetry API

A future HTTP ingestion endpoint should accept telemetry from systems that do not use MQTT.

Proposed endpoint:

POST /api/ingest

Suggested payload:

{
  "source_type": "http",
  "source_id": "air_quality_api",
  "stream_id": "station_001.pm25",
  "timestamp": "2026-05-13T12:00:00Z",
  "value": 13.2,
  "tags": {
    "parameter": "pm25",
    "city": "Chicago",
    "unit": "µg/m3"
  }
}
Dataset Replay

Dataset replay should be used for demos and benchmarks.

Example command:

python scripts/replay_dataset.py --file data/sample.csv --rate 100
Internal Normalized Format

All source adapters should eventually produce a normalized telemetry event.

class NormalizedTelemetryEvent:
    source_type: str
    source_id: str
    stream_id: str
    topic_or_path: str
    timestamp: str
    value: float
    tags: dict
    raw_payload: dict

This allows MQTT, HTTP, and dataset replay to use the same storage, duplicate detection, class recommendation, and visualization pipeline.
