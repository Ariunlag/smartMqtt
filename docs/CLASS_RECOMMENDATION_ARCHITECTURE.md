# Pair-level class recommendation architecture

SmartMQTT recommends existing Saved Classes for MQTT streams. The PostgreSQL
`classes` and `class_topics` tables are the only class ontology and membership
source of truth. Recommendation state is derived from those records; it never
creates a second class catalog.

## Processing flow

```text
MQTT message
  ├─ canonical identity guard
  ├─ topic discovery and authoritative flat topic embedding
  ├─ InfluxDB persistence
  ├─ WebSocket broadcast
  └─ bounded topic-aware recommendation sidecar
       ├─ deterministic tag/field profiling
       ├─ one independent record per key:value pair
       ├─ batched five-view embedding
       ├─ exact affected-class prototype rebuild
       └─ versioned recommendation-cache invalidation

Saved Class membership
  ├─ compact per-role pair prototypes
  └─ one stream-context centroid from existing flat topic vectors

Candidate topic
  ├─ candidate pair × class prototype cosine evidence
  ├─ deterministic greedy one-to-one matching
  ├─ coverage and unmatched evidence
  ├─ five pair-channel means
  ├─ shared stream-context cosine
  └─ equal mean of valid channels
```

The primary MQTT/Influx path does not depend on recommendation success. The
sidecar has a bounded queue and coalesces pending observations by topic so a
newer observation replaces stale pending work for that topic.

## Pair contract

Every tag and field remains independently identifiable by canonical topic,
original topic, source, raw and normalized key/value, datatype, numeric flag,
and representation version. The five dense embedding views are:

1. `key`
2. `value`
3. `key_value`
4. `schema`
5. `numeric_key`, only for numeric pairs

No lexical fallback, synonym dictionary, string-distance score, or concatenated
whole-stream pair view is used. One model batch may contain many texts, but
every returned vector maps back to one pair and one view.

The sixth class-level channel is `stream_context`. It reuses the authoritative
flat vector produced by `EmbeddingManager.embed_flattened_topic()` for duplicate
detection. It is not embedded or stored a second time for recommendation.

## Prototypes and matching

A prototype identity is `(class_id, source, normalized_key, datatype)`. Keys
such as `temp`, `temperature`, and `heat_level` remain separate prototypes.
Each compact prototype contains five centroids at most, a member count, and a
prototype version. Raw member vectors remain solely in the pair embedding
store.

For a candidate pair and class prototype, compatibility is the mean of valid
pair-view cosine scores. All candidate/prototype compatibilities are ordered by
descending score, then stable pair and prototype identities. A match is
accepted only if neither side was previously matched. Candidate coverage and
prototype coverage are reported separately; unmatched pairs and prototypes are
retained in the response.

Class channel scores are means over matched evidence. An unavailable numeric
channel is `null`, never fabricated as zero. The overall similarity is an equal
mean of valid class channels. It is a similarity score, not a probability.

## Version and action contract

Each canonical topic has a representation version. Rapid numeric value changes
do not repeatedly rebuild representation state; key, datatype, source, schema,
and stable categorical changes do. Each class has a profile version that
increments for membership, canonical remap, or representation-relevant profile
changes.

Recommendation identity includes canonical topic, topic version, class ID,
class profile version, and algorithm version. Accept/reject/dismiss requests
must present the current identity; stale actions receive HTTP 409.

- `RECOMMENDATION_ACCEPT` adds membership and records recommendation evidence.
- `RECOMMENDATION_REJECT` stores a version-scoped negative constraint.
- `RECOMMENDATION_DISMISS` hides only that unchanged version and is not a label.
- `MANUAL_ADD` and `MANUAL_REMOVE` change membership with distinct provenance.
- duplicate confirm and keep-both actions remain separate identity decisions.

Audit rows are append-only and contain factual versions, scores, coverage, and
matched identities. They contain no dense vectors or generated explanations.

## Storage classification and migration map

| Object | Classification | Current role |
| --- | --- | --- |
| PostgreSQL `classes`, `class_topics` | Source of truth | Class identity and ordered canonical membership |
| PostgreSQL `duplicate_canonical_topics` | Source of truth | Direct canonical roots; alias chains are forbidden |
| PostgreSQL `duplicates` | Source of truth | Pending and terminal duplicate decisions |
| PostgreSQL `topic_representations` | Derived persistent state | Pair contract fingerprint and topic version |
| PostgreSQL `class_recommendation_constraints` | Human decision | Version-scoped rejection evidence |
| PostgreSQL `class_recommendation_dismissals` | Product state | Hide-until-change state, not model training |
| PostgreSQL `class_recommendation_actions` | Audit | Append-only factual action provenance |
| PostgreSQL `semantic_application_state` | Legacy migration | Preserved non-destructively; production no longer reads or writes it |
| Qdrant `topic_embeddings` | Shared derived evidence | Authoritative duplicate and stream-context vector |
| Qdrant `tag_key_value_embeddings` | Derived exploratory evidence | Existing Tag Groups only; not a recommendation channel |
| Qdrant `tag_group_centroids` | Derived exploratory state | Existing Tag Groups only |
| Qdrant `class_pair_embeddings` | Derived persistent evidence | One raw vector per canonical pair/view |
| Qdrant `class_pair_prototypes` | Derived materialization | Compact per-role centroid points |
| Qdrant `class_stream_context_prototypes` | Derived materialization | One shared-context centroid per class |
| Qdrant `stream_representation_embeddings` | Legacy migration | Preserved in existing deployments; production no longer reads or writes it |
| In-memory recommendation cache | Derived cache | Version-keyed deterministic results |

The migration is non-destructive. It adds IDs, versions, action tables, and new
derived vector collections. It stops legacy reads/writes but does not drop the
legacy PostgreSQL table or old Qdrant collection. No volume reset is required.

## Module disposition

The pre-refactor package was classified before removal:

- **Moved:** deterministic profiler and temporal stability logic to
  `services/class_recommendation`; RQ1 dataset leakage controls to the research
  evaluation subpackage.
- **Retained:** embedding model, authoritative flat topic vector, cosine and
  centroid concepts, canonical identity, duplicate lifecycle, Tag Groups,
  MQTT/Influx/WebSocket paths, Saved Classes, and all intentional dashboard and
  graph work.
- **Research:** prior open-world documents moved under
  `docs/research/archive/` and clearly marked historical.
- **Removed:** production discovery pool, clustering, open-world decision
  lifecycle, separate review/catalog API and UI, six flattened stream-view
  runtime, snapshot workers, and tests that only asserted those retired paths.

## APIs

- `GET /api/classes/`
- `POST /api/classes/`
- `PUT /api/classes/{name}`
- `DELETE /api/classes/{name}`
- `GET /api/topics/{topic}/class-recommendations`
- `GET /api/classes/{name}/recommendations`
- `POST /api/classes/{name}/recommendation-actions`
- `GET /api/class-recommendations/status`

Recommendation responses expose pair identities, actual cosine evidence,
coverage, unmatched evidence, versions, and pending duplicate state. They do
not expose vectors, model internals, credentials, DSNs, or SQL.
