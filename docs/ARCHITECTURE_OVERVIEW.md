# SmartMQTT Architecture Overview

SmartMQTT ingests schema-flexible MQTT telemetry, stores time-series values,
detects possible duplicate topics, groups tags, and lets operators maintain
named Saved Classes. Saved Classes are the only production class ontology.

## Runtime flow

1. MQTT subscription and parsing validate each message.
2. The ingestion pipeline persists telemetry to InfluxDB and emits WebSocket
   updates.
3. The existing topic embedding supports duplicate detection.
4. Pair-level recommendation processing profiles each tag and field without
   changing ingestion success or Saved Class membership.
5. Operators inspect deterministic evidence and explicitly accept, reject,
   dismiss, add, or remove a class member.

Recommendation processing is a sidecar. Queue pressure or recommendation
failure cannot change the primary MQTT/InfluxDB outcome.

## Class recommendation model

Each `(source, key, datatype)` identity remains an independent unit. A topic
with three key/value pairs therefore has three pair identities. Each identity
may provide five separately embedded views:

- `key`
- `value`
- `key_value`
- `schema`
- `numeric_key` for numeric fields

The existing duplicate topic vector is reused as the optional sixth
`stream_context` channel. No second flattened topic vector is generated.

Saved Class members contribute compact per-identity, per-view centroids.
Candidates are matched to prototypes using deterministic greedy one-to-one
matching. The score is the equal mean of valid channels and is accompanied by
pair matches, unmatched identities, and coverage. There is no lexical fallback
and no automatic class creation.

See [CLASS_RECOMMENDATION_ARCHITECTURE.md](CLASS_RECOMMENDATION_ARCHITECTURE.md)
for the exact data contracts, persistence classification, APIs, versioning,
duplicate reconciliation, and action behavior.

## Storage ownership

- PostgreSQL: subscriptions, Saved Classes, class membership, duplicate state,
  canonical topic identity, versions, recommendation constraints/dismissals,
  and append-only action audit.
- InfluxDB: telemetry values.
- Qdrant: authoritative duplicate/tag vectors, pair embeddings, and derived
  compact class prototypes.
- Frontend state: transient presentation state only.

The legacy `semantic_application_state` table remains only because migration
history is non-destructive. No production code reads it.

## User interface

The existing redesigned dashboard, graphs, topic controls, duplicate workflow,
tag groups, and Saved Classes remain. The retired review/operations experience
is replaced by an additional Recommendations view that exposes real pair,
prototype, channel, coverage, version, and duplicate-pending evidence without
exposing vectors or model internals.

## Evaluation and operations

- Pair-level RQ1 evaluation is documented in
  [research/RQ1_PAIR_RECOMMENDATION.md](research/RQ1_PAIR_RECOMMENDATION.md).
- Non-destructive full-stack acceptance is documented in
  [REAL_STACK_ACCEPTANCE.md](REAL_STACK_ACCEPTANCE.md).
- Deployment and persistence details are in [deployment.md](deployment.md) and
  [PERSISTENCE.md](PERSISTENCE.md).
