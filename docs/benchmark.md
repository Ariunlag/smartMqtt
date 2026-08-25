# Benchmark Plan

SmartMQTT benchmarks keep operational throughput, duplicate detection, and
class recommendation evaluation separate so one metric cannot hide a failure
in another subsystem.

## Operational metrics

- MQTT messages submitted, processed, failed, coalesced, and dropped.
- Per-topic ordering and same-topic concurrency safety.
- InfluxDB write latency and retained point count.
- WebSocket delivery and dashboard load time.
- Restart recovery from durable PostgreSQL and Qdrant state.

## Duplicate metrics

- Candidate detection latency.
- Precision and recall where labeled pairs exist.
- Pending, keep-both, and confirmed action counts.
- Canonical remapping and Saved Class membership reconciliation.

Duplicate metrics use the established flattened topic vector and signal
correlation path. They are not class-recommendation scores.

## Pair-level class recommendation metrics

- Per-view top-1 accuracy and macro-F1.
- Class-ranking accuracy.
- Pair coverage and unmatched candidate/prototype identities.
- Ranking change from adding the existing `stream_context` channel.
- Embedding calls and generated pair-vector counts.
- Profile rebuild and cache-invalidation counts.

The controlled RQ1 runner uses leakage-safe class/topic grouping and reports
the five independent pair views plus optional stream context. It does not
automatically select a production threshold or create a class.

See [research/RQ1_PAIR_RECOMMENDATION.md](research/RQ1_PAIR_RECOMMENDATION.md)
for the reproducible protocol.
