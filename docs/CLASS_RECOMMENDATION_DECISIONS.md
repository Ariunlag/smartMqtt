# Class recommendation decisions

## Saved Classes are authoritative

The existing class tables and APIs define identity and membership. Derived
profiles never become a second ontology, and Tag Groups remain an independent
exploratory feature.

## Pair identity precedes aggregation

Tags and fields are independent key:value units. Aggregation occurs only after
pair-to-prototype matching. This prevents unrelated roles such as location,
status, unit, temperature, and humidity from being averaged into one opaque
topic centroid.

## Five dense views, no lexical fallback

All pair similarities are cosine similarities over model embeddings. A model or
storage failure is explicit. Raw text is retained only to identify the compared
evidence.

## Conservative prototype identity

Prototype identity uses source, normalized key, and datatype. Similar-looking
keys are not merged automatically. This keeps human membership authoritative
and makes every centroid reproducible from raw pair embeddings.

## Deterministic greedy one-to-one matching

The baseline avoids a new optimization dependency. Stable score and identity
ordering prevents one class prototype from being claimed by multiple candidate
pairs and makes repeated runs identical.

## Equal mean of valid channels

No hand-tuned production weights are claimed. Missing numeric evidence remains
unavailable. RQ1 may compare conditions, but held-out results do not silently
change production fusion.

## Versioned suppression and stale-action rejection

Reject and dismiss apply only while both topic and class versions are unchanged.
Dismiss is product state, not training evidence. The server rejects stale
recommendation actions and requires a refresh.

## Duplicate identity remains independent

Pending and keep-both topics remain independently eligible. Confirmed aliases
stop independent membership and prototype contribution, remap to the canonical
root, and invalidate affected profiles. Canonicalization can operate without a
recommendation runtime; derived profile reconciliation is an optional callback.

## Non-destructive legacy preservation

Legacy persistence objects are no longer live, but are not dropped in this
migration. Operators can validate and migrate historical data before any later
explicit cleanup.
