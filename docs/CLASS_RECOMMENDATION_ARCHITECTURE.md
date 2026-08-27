# System recommended-class architecture

SmartMQTT has two deliberately separate class concepts.

1. **Saved Classes** are created and edited by the user. PostgreSQL `classes` and
   `class_topics` remain their source of truth. The Class Builder and Saved Classes
   UI own this workflow.
2. **Recommended Classes** are system-derived candidate topic groups. They are
   discovery output, not Saved Classes, and are never inserted into `classes` or
   `class_topics` merely because the system found them.

The dashboard recommendation path must not present an existing Saved Class as a
system recommendation. Manual Saved Classes may later be used as supervised evidence
for learning, but that is a separate feedback policy.

## Processing flow

```text
MQTT message
  ├─ canonical duplicate-identity guard
  ├─ authoritative flat stream embedding
  ├─ InfluxDB persistence
  ├─ WebSocket broadcast
  └─ bounded pair-evidence sidecar
       ├─ deterministic tag/field profiling
       ├─ one independent record per key:value pair
       ├─ five pair embedding views
       └─ versioned evidence persistence

Active canonical topics
  ├─ key evidence
  ├─ value evidence
  ├─ key + value evidence
  ├─ schema evidence
  ├─ numeric-key evidence when applicable
  └─ shared whole-stream context evidence
       ↓
independent per-channel candidate discovery
       ↓
merge identical member sets as multi-channel consensus
       ↓
Recommended Class candidates
```

Confirmed duplicate aliases never contribute as independent candidate members.
Pending duplicate topics stay eligible and carry a pending-review flag.

## Evidence contract

Every tag and field remains an independent pair identified by canonical topic,
original topic, source (`tag` or `field`), normalized key, datatype, numeric state,
and representation version.

The five pair views are `key`, `value`, `key_value`, `schema`, and `numeric_key` for
numeric pairs only. The sixth channel is `stream_context`, reusing the authoritative
flat topic vector already produced for duplicate detection.

`tag` and `field` are pair sources, not extra embedding channels. The UI groups pair
evidence by source so tag evidence and field evidence remain understandable.

## Discovery and ranking

Candidate discovery runs independently for each of the six evidence channels. The
baseline uses HDBSCAN over a precomputed cosine-distance matrix for each channel.
There is no hand-tuned weighted fusion and no global user-facing average similarity.

If the exact same topic membership is independently discovered by multiple channels,
those channels are attached to one candidate as consensus reasons. Candidate ordering
is deterministic: more supporting channels first, then larger membership, then stable
topic ordering.

A scalar compatibility is allowed internally only to make pair-to-pair one-to-one
assignment deterministic. It is not presented as recommendation confidence.

## User-facing explanation

The Recommendations UI shows:

- which channels independently discovered the group,
- suggested member topics,
- matched pair coverage,
- tag pair evidence,
- field pair evidence,
- individual key/value/key+value/schema/numeric-key cosine scores,
- whole-stream context similarity,
- pending duplicate-review state.

The UI does not reduce those facts to one `Overall similarity` number.

## Human feedback boundary

Candidate review remains separate from Saved Class membership. A later feedback layer
will persist keep/add/remove/reject decisions as supervised candidate evidence. An
accepted candidate may optionally be saved into a user-owned class, but it is not a
Saved Class before that explicit action.

## Duplicate boundary

Duplicate detection is an identity workflow, not a class workflow.

- `PENDING`: both topics remain independently active; recommendation only displays a
  pending flag.
- `NOT_DUPLICATE`: both remain independent.
- confirmed duplicate: the alias stops independent processing and candidate
  contribution; the canonical root remains active.

## Persistence

PostgreSQL is now both the relational source of truth and the dense-vector store via
pgvector. HNSW cosine indexes back topic ANN search, pair evidence, tag evidence, and
prototype material. InfluxDB remains the telemetry time-series store.

The vector schema currently enforces 384 dimensions. A model-dimensionality change
requires an explicit migration rather than silently mixing vector shapes.

The compatibility module `services.database.qdrant` temporarily re-exports the
PostgreSQL vector adapter so older store imports do not require a flag-day rewrite; it
does not connect to Qdrant.

## APIs

User-owned Saved Classes remain under:

- `GET /api/classes/`
- `POST /api/classes/`
- `PUT /api/classes/{name}`
- `DELETE /api/classes/{name}`

System discovery is exposed through:

- `GET /api/recommended-classes`
- `GET /api/class-recommendations/status`

Older Saved-Class matching endpoints are retained temporarily for compatibility but
are not the dashboard Recommended Classes workflow.
