# Recommended-class decisions

## Saved Classes and Recommended Classes are separate

**Decision:** `classes` and `class_topics` describe only user-owned Saved Classes.
System-derived recommendation candidates are a separate workflow and must not be
presented as existing Saved Classes.

**Reason:** Manual classes are explicit user organization. A system candidate is
hypothesis/evidence that the user may edit or reject. Mixing them makes provenance
ambiguous and prevents clean feedback learning.

## Pair identity precedes aggregation

Tags and fields remain independent key:value units. Evidence is matched pair-to-pair
before any channel summary is calculated. A shared tag does not automatically make
whole streams equivalent.

## Six evidence channels stay visible

The five pair views are `key`, `value`, `key_value`, `schema`, and `numeric_key` when
numeric. `stream_context` is the sixth channel and reuses the existing flat topic
embedding.

`tag` and `field` remain evidence sources, not extra views.

## Do not explain recommendations with one average

**Decision:** Do not use a fused overall similarity as the user-facing explanation.
Preserve independent channel evidence, pair-level scores, and coverage.

A scalar may still be used internally for deterministic one-to-one pair assignment.
Candidate ordering may also use deterministic non-weighted rules, but neither is a
claim that one averaged number represents recommendation confidence.

## Discover candidates independently by channel

**Decision:** Run discovery independently for each evidence channel. The baseline uses
HDBSCAN with a precomputed cosine-distance matrix. If multiple channels discover the
same exact member set, merge the evidence into one candidate and report all supporting
channels.

This preserves disagreement between representations instead of hiding it inside a
weighted score.

## Human edits are future learning evidence

Candidate membership review should preserve:

- kept topics as positive evidence,
- user-added topics as positive evidence,
- removed topics as negative/correction evidence,
- reject/dismiss as explicit candidate-level decisions.

Those decisions are separate from Saved Class membership. Manually created Saved
Classes can later be used as additional supervised examples, but that learning policy
must be explicit and versioned.

## Duplicate identity remains independent

Pending and keep-both topics remain independently eligible. Confirmed aliases stop
independent candidate contribution. Duplicate decisions do not automatically create,
merge, or name recommended classes.

## Persistence changes do not change semantics

A later Qdrant-to-pgvector migration may simplify storage and transactions. It must
preserve independent pair evidence, candidate provenance, manual Saved Classes, and
system Recommended Classes as separate concepts.
