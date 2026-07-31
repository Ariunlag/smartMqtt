# SmartMQTT Semantic Roadmap

## Purpose

The long-term goal is for SmartMQTT to organize heterogeneous, evolving MQTT
streams semantically without requiring a fixed domain-specific taxonomy or
manually tuned representation weights. The system should gradually adapt to a
deployment environment using stream observations, semantic evidence, and
confirmed feedback.

This document describes a target research direction, not a claim that the full
system has been implemented.

## Target architecture

```text
MQTT observations
        |
        v
Snapshot StreamProfiler
        |
        v
Temporal Stream Profile
        |
        v
Semantic Change Analyzer / Refresh Policy
        |
        v
Stability-aware semantic representations
        |
        v
Six representation embeddings
        |
        v
Representation-specific class evidence
        |
        v
Multi-view consensus
        |
        v
KNOWN / UNCERTAIN / UNKNOWN
        |
        v
UNKNOWN pool
        |
        v
HDBSCAN candidate-class discovery
        |
        v
Confirmation / feedback
        |
        v
Centroid or prototype updates
        |
        v
Representation reliability learning
```

Only the foundation stages identified as completed below currently exist.
Temporal analysis, decision policies, discovery, feedback, and reliability
learning are planned stages.

## Implementation status

### Completed foundation

- [x] Deterministic snapshot stream profiling
- [x] Six deterministic textual representations
- [x] Multi-representation embedding service
- [x] Representation embedding persistence foundation
- [x] Stream semantic pipeline orchestration
- [x] Stream semantic class domain model
- [x] Centroid computation
- [x] Incremental centroid update
- [x] Cosine similarity
- [x] Deterministic known-class ranking

These are isolated building blocks. The new semantic pipeline is not currently
wired into the default production MQTT ingestion path.

### Planned work

- [ ] Temporal stream profile
- [ ] Metadata/schema change evidence tracking
- [ ] Semantic refresh policy
- [ ] Stability-aware representation generation
- [ ] Representation-specific class scoring
- [ ] Multi-view consensus
- [ ] KNOWN / UNCERTAIN / UNKNOWN decision policy
- [ ] UNKNOWN stream pool
- [ ] HDBSCAN candidate-class discovery
- [ ] Human/system confirmation flow
- [ ] Feedback-driven online class updates
- [ ] Representation reliability learning
- [ ] Multi-prototype semantic classes
- [ ] Research/diagnostic backend API
- [ ] Research/diagnostic React UI
- [ ] Production MQTT integration of the new semantic pipeline

## Known-class matching and unknown-class discovery

Known semantic classes are initially intended to use centroid-based matching.
A later extension may use multiple prototypes when one class has a multimodal
embedding distribution.

Streams with weak evidence should not be forced into the nearest known class.
They should accumulate in an UNKNOWN pool, where HDBSCAN is a candidate method
for discovering stable clusters that may become semantic classes after
confirmation.

Centroids or prototypes and clustering solve different problems:

- Centroids or prototypes support matching against known classes.
- HDBSCAN is planned for novel or unknown-class discovery.

HDBSCAN and the UNKNOWN workflow are not currently implemented.

## Temporal semantic direction

A single observation cannot reliably distinguish ordinary measurement changes
from meaningful semantic change. The planned temporal layer will distinguish
evidence such as:

- Ordinary measurement variation: `temperature 22.1 -> 22.8`
- Contextual metadata change: `location room_a -> room_b`
- Schema evolution: `temp -> temperature`, a key appearing, or a key
  disappearing
- Type change: numeric to string
- Stable semantic metadata change: `unit C -> F`

The target flow is:

```text
Raw observations
    -> bounded temporal evidence
    -> semantic stability/change decision
    -> selective representation refresh
```

Not every MQTT message should cause re-embedding. Temporal profiling and the
refresh policy are planned design work and are not part of the current
production path.

## Representation strategy

The current representation builder produces six deterministic views:

- `value_only`
- `key_only`
- `key_value`
- `schema`
- `numeric_key_only`
- `topic_key_value`

The project intentionally does not assign arbitrary hand-tuned weights such as
`0.5 * key_only + 0.3 * schema + ...`. Representation usefulness may vary by
stream and deployment, so the planned progression is:

1. Fixed-representation baselines
2. Representation-specific class evidence
3. Equal or consensus-based multi-view reasoning
4. Temporal and stability-aware selection
5. Feedback-derived representation reliability
6. Learned weighting only if experiments justify it

Learned weighting does not currently exist.

## Research hypothesis

Current hypothesis:

> Temporal stability-aware use of multiple semantic representations can
> improve organization and class recommendation for heterogeneous, evolving
> IoT streams compared with relying on a single static textual representation.

The open-world direction is for SmartMQTT to bootstrap and incrementally refine
semantic stream organization in a new deployment with limited supervision.
These statements are hypotheses and design goals; experimental superiority or
novelty has not been established.

## Planned evaluation

Planned comparisons include individual fixed representations, equal multi-view
consensus, stability-aware representation selection, and feedback-derived
representation reliability.

Planned scenarios include:

- Ordinary numeric value variation
- Identifier variation
- Categorical metadata change
- Key addition or removal
- Schema or key rename
- Type change
- Gradual metadata drift
- New unseen semantic classes

Candidate metrics include:

- Top-1 class accuracy
- Macro-F1
- Recall@K
- Mean reciprocal rank (MRR)
- Class consistency under benign drift
- False semantic refresh rate
- Drift detection delay
- Unknown detection precision and recall
- Candidate-cluster quality
- Embedding refresh count
- Latency and cost

No results are reported here; this section defines planned evaluation.

## Documentation maintenance

For every future semantic pull request:

- Read `README.md`.
- Read `docs/SEMANTIC_ROADMAP.md`.
- Read `docs/SEMANTIC_DECISIONS.md`.
- If the pull request completes or changes a roadmap item, update
  `docs/SEMANTIC_ROADMAP.md` in the same pull request.
- If the pull request changes an architecture or research decision, update
  `docs/SEMANTIC_DECISIONS.md` in the same pull request.

`README.md` should describe only behavior and components that actually exist.
Planned functionality must not be documented as implemented. The repository is
the project source of truth; external assistant memory must not be required to
reconstruct the architecture.
