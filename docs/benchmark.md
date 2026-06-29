# Benchmark Plan

This document defines the benchmark plan for Smart-MQTT++.

## Benchmark Goals

The benchmark should measure whether Smart-MQTT++ can ingest, store, analyze, and visualize schema-flexible IoT telemetry streams efficiently.

## Metrics

### Ingestion Metrics

- Messages per second.
- Number of active topics.
- Average payload size.
- InfluxDB write latency.
- Dropped or failed messages.

### Semantic Processing Metrics

- Embedding generation latency.
- Duplicate detection latency.
- Number of duplicate candidates.
- Precision and recall for duplicate detection where labels are available.
- Class recommendation quality.

### Dashboard Metrics

- WebSocket event latency.
- Number of connected clients.
- Chart update responsiveness.

## Test Scenarios

### Scenario 1: Small Local Demo

- 10 topics.
- 1 message per second per topic.
- Duration: 5 minutes.

### Scenario 2: Medium Load

- 100 topics.
- 5 messages per second per topic.
- Duration: 10 minutes.

### Scenario 3: High Topic Count

- 1,000 topics.
- 1 message per second per topic.
- Duration: 10 minutes.

### Scenario 4: Duplicate Detection Evaluation

- Generate topic pairs with similar names and similar numeric signals.
- Generate topic pairs with similar names but different numeric signals.
- Generate topic pairs with different names but correlated numeric signals.
- Evaluate hybrid scoring behavior.

### Scenario 5: Class Recommendation Evaluation

- Generate tags representing locations, device types, and domains.
- Measure whether semantically related tags are grouped correctly.

## Benchmark Output

Each benchmark run should generate:

```text
benchmark_results/
  run_metadata.json
  ingestion_metrics.csv
  semantic_metrics.csv
  websocket_metrics.csv
  summary.md
Reporting Rules

Do not claim a throughput number in README or papers unless it is produced by a reproducible benchmark run.

Every benchmark result should include:

Hardware details.
OS.
Python version.
Node version.
MQTT broker.
InfluxDB version.
Number of topics.
Message rate.
Duration.
