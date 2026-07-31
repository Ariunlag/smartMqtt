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
TemporalStreamProfiler
        |
        v
TemporalProfileUpdate
        |
        +--> SemanticRefreshPolicy
        |           |
        |           v
        |    SemanticRefreshDecision (when)
        |
        +--> TemporalStreamProfile
                    |
                    v
         StabilityAwareRepresentationBuilder (what)
        |
        v
Six representation embeddings
        |
        v
RepresentationClassEvidenceMatrix
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
Automatic builder invocation, embedding refresh integration, multi-view
consensus, class decision, discovery, feedback, and reliability learning remain
planned stages.

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
- [x] Temporal stream profile
- [x] Metadata/schema change evidence tracking
- [x] Semantic refresh policy
- [x] Stability-aware representation generation
- [x] Representation-specific class scoring

These are isolated building blocks. The new semantic pipeline, temporal
profiler, refresh policy, stability-aware builder, and representation class
scorer are not currently wired into the default production MQTT ingestion path.

### Planned work

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
from meaningful semantic change. The temporal profiling foundation now records
bounded evidence across repeated observations, including value changes, type
changes, key appearance or absence, and stable categorical value changes with
hysteresis. It now records stable categorical establishment and replacement,
as well as key reappearance after an absence.

Examples of evidence include:

- Ordinary measurement variation: `temperature 22.1 -> 22.8`
- Contextual metadata change: `location room_a -> room_b`
- Schema evolution: a key appearing or a key disappearing
- Type change: numeric to string
- Stable semantic metadata change: `unit C -> F`

The temporal profiler records this evidence. The deterministic
`SemanticRefreshPolicy` now converts each `TemporalProfileUpdate` into an
explainable `SemanticRefreshDecision`:

```text
Raw observations
    -> bounded temporal evidence
    -> deterministic semantic refresh decision
    -> stability-aware semantic text
    -> embedding refresh integration (planned)
```

The current policy requests initialization on the first observation, ignores
raw value changes alone, responds to structural and stable categorical changes,
and requires a configurable persistence threshold for a missing key. A key
that reappears requests refresh only if its prior missing streak reached that
threshold. Together, the temporal profiler and policy cover the lifecycle
evidence consumed by the stability-aware builder: first stable categorical
value, stable replacement, persistent disappearance, and reappearance after
persistent disappearance. `SemanticRefreshPolicy` decides when rebuilding is
justified;
`StabilityAwareRepresentationBuilder` determines the stable semantic text from
`TemporalStreamProfile`. Automatic invocation and re-embedding are not
integrated, and these components remain isolated from the production MQTT path.

## Representation strategy

The current representation builder produces six deterministic views:

- `value_only`
- `key_only`
- `key_value`
- `schema`
- `numeric_key_only`
- `topic_key_value`

The representation class scorer compares each embedded view only with the
same-view centroid of every known class. It returns an independent cosine score
for every representation-by-class pair. No combined class score, weighting,
consensus, or final class decision currently exists.

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
