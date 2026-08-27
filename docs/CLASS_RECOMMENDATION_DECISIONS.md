# Recommended Class decisions

## Saved Classes and Recommended Classes remain separate

`classes` and `class_topics` describe user-owned Saved Classes only. System candidates
are hypotheses produced from evidence and must not become Saved Classes without an
explicit user action.

## Pair identity is never flattened during representation

Every tag and field remains an independent pair. Each pair has independent `key`,
`value`, `key_value`, and `schema` vectors. `stream_context` is stream-scoped evidence.

A stream with multiple pairs therefore produces multiple independent pair records;
those records are not averaged into one representation vector.

## Generate evidence first; choose algorithms later

The representation layer must not decide which evidence is most important. All
registered evidence is stored independently. Recommendation strategies consume the
same evidence snapshot and may experiment with subsets, weighting, clustering,
centroids/prototypes, hybrid methods, or learned ranking.

Adding or changing a decision strategy must not require regenerating embeddings unless
the representation contract itself changes.

## Tag grouping reuses shared value evidence

The original tag-value centroid behavior is not a separate embedding system. The
exploratory tag-group feature consumes the existing tag pair `value` vector and updates
its centroid from that shared evidence.

There is no second tag-specific embedding pipeline.

## Current baseline strategy

The current production strategy is `independent_hdbscan`. It runs HDBSCAN separately
for each registered evidence id and merges exact identical memberships as consensus.
It does not fuse or weight evidence channels.

This is a baseline strategy, not a permanent statement that HDBSCAN is the only valid
recommendation method.

## Centroids belong in the strategy layer

A centroid/prototype strategy should preserve pair roles and evidence ids. Separate
centroids may exist for `key`, `value`, `key_value`, `schema`, and stream context.
Different semantic pair roles must not be collapsed into one global centroid.

## User-facing explanations remain evidence-first

The default UI should show candidate members, evidence reasons, pair matches, coverage,
and stream evidence. A single fused overall similarity is not the primary explanation.

The dashboard uses one Recommended Classes surface. Strategy selection belongs inside
that surface when more than one strategy is available. Side-by-side algorithm
comparison belongs in a research/evaluation view, not separate end-user recommendation
tabs.

## Human actions become supervised evidence

Future keep/add/remove/reject/dismiss actions should persist the strategy id,
representation/candidate version, evidence scores, and coverage that produced the
recommendation. This creates a dataset for calibrated weighting or ranking models.

Feedback on a system candidate must not silently modify a Saved Class.

## Duplicate identity remains independent

Pending and keep-both topics remain independently eligible. Confirmed aliases stop
independent candidate contribution. Duplicate decisions do not create or merge
Recommended Classes.

## PostgreSQL + pgvector is the vector persistence boundary

Runtime dense-vector persistence uses PostgreSQL + pgvector. Application code imports
the PostgreSQL vector adapter directly; there is no compatibility client or separate
runtime vector service.
