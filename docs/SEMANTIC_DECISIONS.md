# SmartMQTT Semantic Decisions

This record explains the current architecture and research choices behind the
semantic roadmap. Status values distinguish accepted foundations, current
directions, and planned work.

## Decision: Keep production tag groups separate from stream semantic classes

**Status:** Accepted

**Context:** Existing production tag groups record tag key/value relationships.
Stream semantic classes represent entire streams or topics by semantic role.

**Decision:** Keep tag groups and stream semantic classes as separate concepts,
models, and workflows.

**Rationale:** A shared tag does not necessarily imply that two streams have the
same semantic role, and streams can have related roles without identical tags.

**Consequences:** Existing tag-group behavior remains unchanged. Semantic class
work must use separate terminology and must not reinterpret tag-group records.

## Decision: Do not use arbitrary fixed representation weights

**Status:** Accepted

**Context:** The six representations expose different evidence. A fixed formula
such as `0.5 * key_only + 0.3 * schema + ...` would embed undocumented
assumptions into every deployment.

**Decision:** Keep representation evidence separate and begin with individual
baselines and equal or consensus-based treatment. Reliability may later be
derived from confirmed outcomes.

**Rationale:** Hand-tuned weights are difficult to justify scientifically, are
likely domain dependent, can conceal weak representations, and do not support
self-adaptation.

**Consequences:** There is no weighted-fusion default. Learned weighting remains
an experimental option only if evidence justifies it.

## Decision: Use centroids for known classes, not for class discovery

**Status:** Current direction

**Context:** Matching a stream to an established class and discovering a novel
class are different problems.

**Decision:** Use centroid-based similarity for initial known-class matching.
Use a separate discovery mechanism for unknown streams; HDBSCAN is the current
candidate. A known class may later use multiple prototypes if its embedding
distribution is multimodal.

**Rationale:** Centroids are simple, deterministic, inexpensive, and support
incremental online updates. Density-based clustering can discover candidate
structure without requiring every stream to match a known class.

**Consequences:** The current class engine ranks known class centroids only. It
does not discover classes. HDBSCAN and multi-prototype classes are planned, not
implemented.

## Decision: Treat UNKNOWN as a valid semantic state

**Status:** Planned

**Context:** Nearest-class ranking always produces a nearest result even when
all available evidence is weak.

**Decision:** Do not force weak matches into a known class. The intended
decision states are KNOWN, UNCERTAIN, and UNKNOWN.

**Rationale:** An explicit open-world state protects known classes from
unreliable assignments and preserves novel streams for later analysis.

**Consequences:** Thresholds and calibration will require evaluation. The
decision policy and UNKNOWN pool are not currently implemented.

## Decision: Separate snapshot profiling from temporal profiling

**Status:** Current direction

**Context:** The current `StreamProfiler` deterministically describes one
observation. Temporal evidence requires bounded state across observations.

**Decision:** Retain the snapshot profiler and add a separate temporal profiler
in future work.

**Rationale:** Snapshot normalization and structural extraction remain useful,
testable primitives. Temporal state has different lifecycle, storage, and
policy concerns.

**Consequences:** Future temporal work will compose with, rather than replace,
the snapshot profiler. A temporal profiler is not currently present on
`dev-prod`.

## Decision: Do not re-embed every MQTT observation

**Status:** Planned

**Context:** Measurements often change on every message without changing the
stream's semantic identity.

**Decision:** Future refresh decisions should depend on meaningful temporal,
schema, or stable metadata evidence.

**Rationale:** Selective refresh should reduce unnecessary computation and
avoid making semantic state react to ordinary measurement noise.

**Consequences:** A semantic change analyzer and refresh policy must be designed
and evaluated before production integration.

## Decision: Treat representation usefulness as context dependent

**Status:** Current direction

**Context:** Raw values may be weak evidence for a numeric measurement stream,
where keys or schema can be more informative. Stable categorical metadata may
make key/value evidence highly useful.

**Decision:** Do not assume that one representation is globally best.
Eventually derive representation reliability from context and confirmed
outcomes rather than hard-coding it globally.

**Rationale:** Stream structures and deployment vocabularies vary, so the value
of each representation can vary as well.

**Consequences:** Evaluation must report representation-specific behavior.
Adaptive reliability is planned and does not currently exist.

## Decision: Keep the semantic class engine representation-agnostic

**Status:** Accepted

**Context:** Class matching can consume a stream vector or class evidence
regardless of how that evidence was produced.

**Decision:** Keep representation strategy outside the class engine. The engine
must not depend on whether input came from `key_only`, `schema`, weighted
fusion, adaptive selection, or another strategy.

**Rationale:** Separation keeps centroid and similarity behavior deterministic
and lets representation experiments evolve independently.

**Consequences:** Callers are responsible for selecting or combining
representation evidence before class matching. The class engine remains usable
across future representation strategies.

## Research direction

Current hypothesis:

> Temporal stability-aware use of multiple semantic representations can
> improve organization and class recommendation for heterogeneous, evolving
> IoT streams compared with relying on a single static textual representation.

SmartMQTT is intended to bootstrap and incrementally refine semantic stream
organization in a new deployment with limited supervision. This is an
open-world research direction, not a claim of established novelty or measured
superiority.
