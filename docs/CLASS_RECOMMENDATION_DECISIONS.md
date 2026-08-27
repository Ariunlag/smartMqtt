# Recommended-class decisions

## Saved Classes and Recommended Classes are separate

**Decision:** `classes` and `class_topics` describe only user-owned Saved Classes.
System-derived recommendation candidates are a separate workflow and must not be
presented as existing Saved Classes.

**Reason:** Manual classes are explicit user organization. A system candidate is a
hypothesis/evidence that the user may edit or reject. Mixing them makes provenance
ambiguous and prevents clean feedback learning.

## Pair identity precedes aggregation

Tags and fields remain independent key:value units. Evidence is matched pair-to-pair
before any channel summary is calculated. A shared tag does not automatically make
whole streams equivalent.

## Evidence is registry-defined, not numeric-special-cased

The current pair evidence registry contains `key`, `value`, `key_value`, and `schema`.
`stream_context` is the stream-scoped evidence and reuses the existing flat topic
embedding. `tag` and `field` remain pair sources, not extra views.

There is no `numeric_key` evidence channel. Numeric remains a datatype/temporal
property where needed for telemetry handling, but it is not a separate semantic signal.
This avoids counting the same key evidence twice.

Evidence ids, labels, scopes, and pair renderers have one backend registry. Matching,
discovery, prototype construction, evaluation, persistence ordering, and the
Recommendations UI consume that registry/catalog rather than each hard-coding their
own list. A registry change bumps the representation contract and requires
rematerialization of derived evidence.

## Do not explain recommendations with one average

**Decision:** Do not use a fused overall similarity as the user-facing explanation.
Preserve independent channel evidence, pair-level scores, and coverage.

A scalar may still be used internally for deterministic one-to-one pair assignment.
Candidate ordering may use deterministic non-weighted rules, but neither is a claim
that one averaged number represents recommendation confidence.

## Discover candidates independently by channel

**Decision:** Run discovery independently for each registered evidence channel. The
current baseline uses HDBSCAN with a precomputed cosine-distance matrix. If multiple
channels discover the same exact member set, merge the evidence into one candidate and
report all supporting channels.

This preserves disagreement between representations instead of hiding it inside a
weighted score. HDBSCAN remains a baseline; a persistent system-owned candidate/profile
model is a separate follow-up architecture change.

## Human edits are future learning evidence

Candidate membership review should preserve kept topics as positive evidence,
user-added topics as positive evidence, removed topics as correction evidence, and
reject/dismiss as explicit candidate-level decisions.

Those decisions are separate from Saved Class membership. Manually created Saved
Classes can later be used as additional supervised examples, but that learning policy
must be explicit and versioned.

## Duplicate identity remains independent

Pending and keep-both topics remain independently eligible. Confirmed aliases stop
independent candidate contribution. Duplicate decisions do not automatically create,
merge, or name recommended classes.

## PostgreSQL + pgvector is the vector persistence boundary

**Decision:** Dense embedding persistence and ANN search live in PostgreSQL using
pgvector HNSW cosine indexes. InfluxDB remains the telemetry store.

This removes the separate Qdrant runtime dependency, permits SQL-side payload deletes
instead of application collection scans, and puts vector material in the same database
as version/membership/audit metadata. The current vector dimension is explicitly 384;
a model-dimension change requires a schema migration.

The storage layer must not change the semantic separation between Saved Classes and
Recommended Classes or collapse the registered evidence channels.
