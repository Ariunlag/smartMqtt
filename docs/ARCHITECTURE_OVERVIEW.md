# SmartMQTT Architecture Overview

SmartMQTT ingests schema-flexible MQTT telemetry, stores time-series values, detects
possible duplicate topics, preserves independent semantic evidence for every tag and
field pair, and supports both user-owned Saved Classes and system-derived Recommended
Classes.

## Runtime flow

1. MQTT subscription and parsing validate each message.
2. Canonical duplicate identity is resolved before downstream processing.
3. Telemetry is persisted to InfluxDB and emitted over WebSocket.
4. One authoritative `stream_context` vector supports duplicate ANN search and
   stream-level recommendation evidence.
5. A bounded sidecar materializes independent pair evidence for every tag and field.
6. Recommendation strategies consume the stored evidence without changing how vectors
   are generated.

Queue pressure or recommendation failure does not change the primary MQTT/InfluxDB
outcome.

## Pair evidence

Each `(source, normalized_key, datatype)` identity remains independent. Every pair has
four separately embedded views:

- `key`
- `value`
- `key_value`
- `schema`

`tag` and `field` are sources, not evidence channels. Numeric is datatype metadata.
There is no numeric-specific recommendation vector.

## Recommended Class strategies

The evidence layer is strategy-agnostic. Two baselines are registered over the same
stored vectors:

- `independent_hdbscan` matches compatible pairs, preserves per-evidence scores and
  coverage, builds one topic-distance matrix per evidence type, runs HDBSCAN on each
  matrix independently, and merges identical memberships as consensus.
- `tag_value_centroid` processes every tag pair independently using only its stored
  `value` vector and assigns that vector to the nearest current centroid when the
  configured cosine threshold is met.

The centroid method is the original tag-value idea expressed as a recommendation
strategy, not a second embedding pipeline or a separate top-level feature.

Future prototype, weighted, hybrid, or learned-ranking strategies use the same stored
evidence. Strategy changes therefore do not require embedding rematerialization.

Saved Classes remain user-owned and separate from system candidates. Older
Saved-Class recommendation endpoints/prototypes are compatibility code and are not the
dashboard Recommended Classes workflow.

## Storage ownership

- PostgreSQL + pgvector: relational metadata, human decisions, canonical identity,
  pair evidence, stream vectors, compatibility prototypes, versions, and audit data.
- InfluxDB: telemetry values and history.
- Frontend state: transient presentation state only.

## User interface

The dashboard has one Recommended Classes surface. It renders backend-provided evidence
and strategy metadata and exposes a method selector when multiple strategies are
registered. Side-by-side algorithm comparison belongs in a separate research/evaluation
view rather than separate end-user recommendation tabs.

See [CLASS_RECOMMENDATION_ARCHITECTURE.md](CLASS_RECOMMENDATION_ARCHITECTURE.md),
[PERSISTENCE.md](PERSISTENCE.md), and [REAL_STACK_ACCEPTANCE.md](REAL_STACK_ACCEPTANCE.md)
for detailed contracts and validation.
