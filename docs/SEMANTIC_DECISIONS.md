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
baselines and equal-view consensus treatment. The implemented
`RepresentationClassScorer` compares each view only with its same-view known-
class centroid and returns six independent scores. The initial consensus
baseline treats all six views equally and preserves view winners, top-1 vote
counts, mean ranks, and raw similarity evidence. It ranks class summaries using
deterministic lexicographic rules rather than a weighted sum. Reliability may
later be derived from confirmed outcomes.

**Rationale:** Hand-tuned weights are difficult to justify scientifically, are
likely domain dependent, can conceal weak representations, and do not support
self-adaptation.

**Consequences:** There is no weighted-fusion default. The scorer and consensus
engine preserve view disagreement and produce evidence rather than a final
class decision. Equal-view consensus is an evaluation baseline, not a claim of
optimality. Future feedback-driven representation reliability may outperform
it and remains a later experimental policy.

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

**Status:** Accepted

**Context:** Nearest-class ranking always produces a nearest result even when
all available evidence is weak.

**Decision:** Do not force weak matches into a known class. The implemented
deterministic policy returns KNOWN, UNCERTAIN, or UNKNOWN. KNOWN requires
explicitly configured agreement, absolute mean-similarity, and ambiguity-
margin criteria. UNKNOWN represents no known classes or clearly weak absolute
evidence. UNCERTAIN covers the middle and ambiguous region.

**Rationale:** An explicit open-world state protects known classes from
unreliable assignments and preserves novel streams for later analysis.

**Consequences:** Thresholds are explicit configuration intended for empirical
calibration; the repository does not prescribe production values. This policy
is a deterministic baseline, not a claim of experimental optimality. It
returns diagnostic candidate evidence but does not assign a class, populate an
UNKNOWN pool, persist results, or integrate with production MQTT processing.

## Decision: Separate snapshot profiling from temporal profiling

**Status:** Accepted

**Context:** `StreamProfiler` deterministically describes one observation,
while temporal evidence requires bounded state across repeated observations.

**Decision:** Retain the snapshot profiler and use a separate
`TemporalStreamProfiler` that consumes snapshot `StreamProfile` observations.

**Rationale:** Snapshot normalization and structural extraction remain useful,
testable primitives. Temporal state has different lifecycle, storage, and
policy concerns.

**Consequences:** The dependency-free temporal profiling foundation now exists
on `dev-prod` and composes with, rather than replaces, the snapshot profiler.
It records bounded value, type, presence, and stable categorical change
evidence, but is not yet integrated into the production MQTT path. Refresh
policy and runtime state ownership remain separate work.

## Decision: Do not re-embed every MQTT observation

**Status:** Accepted

**Context:** Measurements often change on every message without changing the
stream's semantic identity. The temporal profiler can emit raw value evidence
alongside stronger structural or stable categorical evidence.

**Decision:** Use the deterministic `SemanticRefreshPolicy` to decide whether
refresh is warranted:

- Initial observation requests refresh.
- Raw `VALUE_CHANGED` alone does not request refresh.
- `TYPE_CHANGED` requests refresh.
- `STABLE_VALUE_ESTABLISHED` requests refresh when the first categorical value
  completes hysteresis.
- `STABLE_VALUE_CHANGED` requests refresh.
- Post-initial `KEY_ADDED` requests refresh.
- `KEY_MISSING` requests refresh once, when its configurable missing-key
  persistence threshold is reached.
- `KEY_REAPPEARED` requests refresh only when the prior missing streak reached
  that same threshold.

**Rationale:** These explicit rules separate ordinary measurement noise from
initialization, structural evidence, and temporal evidence that has already
passed categorical hysteresis. The missing-key threshold prevents one absent
observation from causing refresh. This is a deterministic starting policy, not
a claim of universal or experimental optimality. The matching reappearance
rule restores symmetry after a key was treated as persistently missing while
ignoring transient absence.

**Consequences:** The dependency-free policy returns an explainable decision
and ordered reasons. It does not rebuild representations, call an embedding
model, persist data, or change the production MQTT path. Stabilized
representation generation, actual re-embedding, threshold evaluation, and
production integration remain separate work.

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

## Decision: Build temporal representations from trusted semantic evidence

**Status:** Accepted

**Context:** The static `RepresentationBuilder` reflects one observation and is
required as a research baseline. Temporal state distinguishes stable evidence
from ordinary value churn, pending categorical candidates, and transient or
persistent key absence.

**Decision:** Keep the snapshot builder unchanged and use a separate
`StabilityAwareRepresentationBuilder` for `TemporalStreamProfile`. The temporal
builder retains transiently missing entries, excludes persistently missing
entries, uses stable categorical values, and ignores pending candidates. It
suppresses numeric field, identifier, and timestamp literals while retaining
their keys and schema. Stable unit values remain usable, and numeric tags are
not assumed to be measurements. No representation weights are introduced.

**Rationale:** These rules produce deterministic text from bounded trusted
evidence without conflating refresh timing with representation content.

**Consequences:** The exclusion threshold should normally match the refresh
policy's missing threshold. These are initial policies to evaluate against the
snapshot baseline, not claims of experimental optimality. The builder does not
embed, persist, score, or integrate with production MQTT processing.

## Research direction

Current hypothesis:

> Temporal stability-aware use of multiple semantic representations can
> improve organization and class recommendation for heterogeneous, evolving
> IoT streams compared with relying on a single static textual representation.

SmartMQTT is intended to bootstrap and incrementally refine semantic stream
organization in a new deployment with limited supervision. This is an
open-world research direction, not a claim of established novelty or measured
superiority.
