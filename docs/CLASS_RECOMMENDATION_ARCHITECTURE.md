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

The five pair views are:

1. `key`
2. `value`
3. `key_value`
4. `schema`
5. `numeric_key` for numeric pairs only

The sixth channel is `stream_context`, reusing the authoritative flat topic vector
already produced for duplicate detection. It is not a duplicate recommendation-only
embedding.

`tag` and `field` are pair sources, not extra embedding channels. The UI groups pair
evidence by these sources so users can see tag evidence separately from field
evidence.

## Discovery and ranking

Candidate discovery runs independently for each of the six evidence channels. The
current baseline uses HDBSCAN over a precomputed cosine-distance matrix for each
channel. There is no hand-tuned weighted fusion and no global user-facing average
similarity score.

If the exact same topic membership is independently discovered by multiple channels,
those channels are attached to one candidate as consensus reasons. Candidate ordering
is deterministic:

1. more independent supporting discovery channels,
2. larger candidate membership,
3. stable topic identity ordering.

A scalar compatibility may be used internally to make pair-to-pair one-to-one
matching deterministic. It is not presented as the reason the class was recommended.

## User-facing explanation

The Recommendations UI shows evidence such as:

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

This change establishes discovery and explanation only. The next feedback layer keeps
candidate review separate from Saved Class membership:

```text
system candidate
  ├─ keep member
  ├─ remove member
  ├─ add member
  ├─ dismiss/reject
  └─ optionally save an accepted result as a user class
```

Kept/added/removed decisions should be persisted as candidate feedback and can later
be used as learning evidence. Existing manually created Saved Classes can also become
supervised examples later, but they are not silently treated as system candidates.

## Duplicate boundary

Duplicate detection is an identity workflow, not a class workflow.

- `PENDING`: both topics stay independently active; recommendation only displays the
  pending flag.
- `NOT_DUPLICATE` / keep-both: both remain independent.
- confirmed duplicate: the alias stops independent processing and candidate
  contribution; the canonical root remains active.

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
are not the dashboard Recommended Classes workflow and should not be used to mix the
two class concepts.

## Persistence direction

The current vector persistence remains unchanged in this semantics/UI commit. A later
persistence change may move vector evidence from Qdrant to PostgreSQL + pgvector.
That migration must not change the class separation or evidence contract described
above.
