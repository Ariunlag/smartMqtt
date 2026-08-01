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

## Decision: Retain UNKNOWN stream evidence without selecting discovery vectors

**Status:** Accepted

**Context:** UNKNOWN streams need an isolated handoff point for future
discovery while retaining the evidence that led to their state.

**Decision:** Retain each UNKNOWN stream in memory by topic with all six current
representation embeddings and its immutable UNKNOWN decision evidence. The pool
replaces an existing topic with its latest entry and does not choose a
representation, combine vectors, or select a discovery algorithm.

**Rationale:** Keeping complete available evidence preserves future experiment
choices without imposing a premature clustering representation or storage
design.

**Consequences:** The pool has no persistence, timestamps, clustering,
candidate-class generation, feedback, or production MQTT integration. This is
a deterministic foundation, not a claim that the retained evidence design is
experimentally optimal.

## Decision: Cluster UNKNOWN evidence independently by representation

**Status:** Accepted

**Context:** UNKNOWN streams may contain candidate structure, but the most
useful representation for discovery has not been established.

**Decision:** Run configurable HDBSCAN independently for each of the six
representation embeddings. Preserve each view's canonical candidate topic
groups and noise topics without fusing vectors, assigning fixed weights, or
forming a cross-view cluster decision.

**Rationale:** Independent results retain disagreement between representation
views and keep future evaluation free to compare discovery strategies.

**Consequences:** A candidate cluster is not automatically a semantic class,
and noise remains valid discovery evidence. HDBSCAN parameters are explicit
configuration that require empirical evaluation; this does not claim HDBSCAN
or any configuration is universally optimal. There is no persistence,
feedback, class creation, or production MQTT integration.

## Decision: Keep candidate confirmation explicit and representation-specific

**Status:** Accepted

**Context:** HDBSCAN provides candidate structure, but cluster output alone is
not sufficient to establish a semantic class.

**Decision:** Record only explicit HUMAN or trusted SYSTEM confirmation or
rejection. A candidate identity consists of its representation name and sorted
member topics, excluding raw HDBSCAN labels and local candidate indexes. The
same topic membership in separate representations remains separate evidence.

**Rationale:** This keeps discovery evidence separate from trusted feedback and
avoids treating SYSTEM as automatic self-confirmation.

**Consequences:** Confirmation does not create or update semantic classes,
centroids, the UNKNOWN pool, or representation reliability. There is no
persistence or production MQTT integration. Class-update policy remains later
work.

## Decision: Update trusted prototypes one representation at a time

**Status:** Accepted

**Context:** A confirmed discovery candidate belongs to exactly one
representation view, while trusted evidence for other views may not exist.

**Decision:** Use confirmed candidate member topics to update only the matching
representation-specific prototype for the confirmed semantic class name. Track
unique accepted topics, apply count-weighted centroid updates, and treat replay
of already accepted topics as idempotent. Do not fabricate missing view
centroids or assemble a full six-view known class from partial evidence.

**Rationale:** This retains trusted cross-view separation and lets evidence
accumulate without making unsupported representation or class assumptions.

**Consequences:** The UNKNOWN pool lifecycle remains separate, and this update
does not remove streams, alter discovery, create class IDs, persist data, or
integrate production MQTT behavior.

## Decision: Preserve editable candidate membership as explicit evidence

**Status:** Accepted

**Context:** A discovered candidate can contain incorrect members or omit a
topic that a HUMAN or trusted SYSTEM reviewer recognizes as belonging to the
chosen semantic class.

**Decision:** Permit candidate membership correction before feedback is saved.
Kept and reviewer-added topics become positive membership evidence; removed
topics become negative membership evidence. Feedback remains specific to the
candidate representation, and ADDED remains distinguishable from KEPT so later
evaluation can measure omissions. Replayed feedback replaces the latest state
for the same topic, class, and representation.

**Rationale:** Explicit member-level evidence preserves the reviewer's decision
without converting it into an undocumented score adjustment. Latest-state
replacement makes replay idempotent while allowing later corrections and
separate class contexts.

**Consequences:** Removed vectors are not subtracted from centroids, and raw
cosine similarities are never manually incremented or decremented. Reviews do
not alter the UNKNOWN pool, prototypes, reliability, clustering, or known-class
assembly. Positive prototype updates, negative-membership constraints, and
representation reliability remain separate follow-up work.

## Decision: Apply reviewed positive membership to all six prototypes

**Status:** Accepted

**Context:** Candidate discovery occurs in one representation, but a reviewed
KEPT or ADDED topic is trusted positive membership for the semantic class as a
complete stream with six independent embeddings.

**Decision:** Use every positive reviewed topic to update each of the six
representation-specific prototypes. The discovery representation does not
restrict the updated views. Representations remain independent: vectors are
neither fused nor assigned fixed weights. Prepare and validate every resulting
prototype before any evidence-store mutation, and treat replay as idempotent.

**Rationale:** Confirmed stream membership supplies matching positive evidence
for every existing representation while atomic preparation prevents a failed
view from leaving partial trusted state.

**Consequences:** REMOVED topics do not update prototypes, but their vectors are
also not subtracted from existing centroids. Correcting membership that was
accepted previously requires later safe retraction or recomputation support.
The UNKNOWN-pool lifecycle remains separate; this operation does not remove
topics, assemble a known class, change similarity, learn reliability, or alter
production processing.

## Decision: Reconcile corrected prototypes by rebuilding final membership

**Status:** Accepted

**Context:** An edited candidate review can remove previously accepted members
as well as keep or add members across the semantic class's six prototypes.

**Decision:** Apply reviewed removal across all six representation prototypes.
For each changed view, derive the final unique member topics and recompute its
centroid from the matching current embeddings retained in the UNKNOWN pool.
Never algebraically subtract removed vectors. Prepare every changed replacement
before mutating the evidence store, and leave unchanged member sets untouched so
replay is idempotent.

**Rationale:** Full arithmetic recomputation is deterministic and avoids the
numerical and provenance ambiguity of reversing an incremental centroid. Using
current pool evidence establishes one explicit rebuild source for every final
member.

**Consequences:** Reconciliation does not preserve historical embedding
snapshots and does not update embeddings itself. Missing or invalid current
evidence aborts all six changes atomically. Negative recommendation constraints,
UNKNOWN-pool lifecycle, reliability statistics, persistence, and production
workflow integration remain separate work.

## Decision: Apply reviewed feedback through class-wide eligibility constraints

**Status:** Accepted

**Context:** Prototype reconciliation applies corrected positive membership, but
a removed topic also needs to remain ineligible for automatic recommendation to
that semantic class until later positive correction.

**Decision:** Record removed membership as a class-wide topic constraint across
all representation views. Apply prototype reconciliation and constraint changes
only after both have been prepared successfully. Later positive feedback for
the same topic and class clears the matching constraint without affecting other
class constraints.

**Rationale:** Eligibility constraints preserve explicit negative feedback
without distorting cosine similarities, votes, ranks, or decision thresholds.
Atomic preparation prevents a failed prototype rebuild from leaving constraint
state inconsistent with trusted evidence.

**Consequences:** Recommendation filtering removes blocked classes while
preserving the original candidate objects and order. If every candidate is
blocked, this component returns no allowed candidates and does not automatically
classify the topic as UNKNOWN. Persistence, API/UI, production integration,
reliability learning, and threshold recalibration remain separate work.

## Decision: Assemble known classes only from complete trusted evidence

**Status:** Accepted

**Context:** The known-class scorer requires an independent centroid for each
of the six representation views, while trusted evidence can accumulate at
different rates for each view.

**Decision:** Materialize a scorer-ready `RepresentationClassCentroids` only
when trusted evidence exists for all six views of the exact semantic class
name. Missing views are never synthesized. The caller supplies `class_id`
explicitly. Assembly reads trusted evidence without modifying it, preserves
independent representation centroids, and performs no weighting, fusion, or
additional centroid computation.

**Rationale:** A complete structural contract avoids representing missing
evidence as a calculated or inferred centroid and keeps semantic evidence
separate from class-identity policy.

**Consequences:** Incomplete evidence returns its missing views in deterministic
order and produces no partial scorer-ready class. Evidence-size acceptance
thresholds remain a separate future policy. Assembly has no persistence,
prototype-update, scoring, consensus, classification, clustering, feedback, or
production MQTT integration.

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

# Diagnostic semantic candidate review

- The API and React screen are diagnostic human-review surfaces, not a production MQTT integration.
- Browser-submitted feedback is always recorded as `HUMAN`; clients cannot claim `SYSTEM` feedback.
- Pending candidate identity is the representation name plus canonical member topics. The discovery candidate index is display metadata only.
- Raw embeddings and prototype centroid vectors are not exposed through the API.
- A successful review atomically applies six-view prototype reconciliation and negative membership constraints through the domain workflow.
- A pending candidate is removed only after its review succeeds. Validation or workflow failures preserve the candidate, prototypes, and constraints.
- The semantic review runtime remains in memory without persistence; pending candidates are now populated automatically from the shared UNKNOWN pool.

## Shared semantic application composition

- One `SemanticApplication` owns the processing runtime, review runtime, and in-memory semantic state for a FastAPI application instance.
- Processing and review use the exact same `UnknownStreamPool`; review updates the application's shared `TrustedClassEvidenceStore` and `NegativeMembershipConstraintStore` through the shared feedback workflow.
- The semantic application is attached to `app.state.semantic_application`. API modules resolve it through FastAPI dependencies and do not create independent production runtimes.
- Reviewed six-view prototypes are atomically synchronized into the processing runtime's explicit known-class registry. Class-name to class-ID mapping remains explicit, and no automatic class ID is generated.
- Negative constraints filter processing-runtime candidate eligibility without changing scores, votes, ranks, similarities, or view winners.

## Production MQTT semantic sidecar

- Semantic processing is a sidecar after the existing TopicHandler, InfluxHandler, and Broadcaster pipeline.
- The Paho callback performs no semantic profiling, embedding, or model work.
- A bounded application-owned queue feeds one ordered semantic worker; submission never waits for embedding completion.
- Semantic processing is enabled by default with a queue capacity of 256 and a five-second shutdown drain timeout; `SEMANTIC_PROCESSING_ENABLED`, `SEMANTIC_QUEUE_MAXSIZE`, and `SEMANTIC_SHUTDOWN_DRAIN_TIMEOUT` provide explicit environment overrides.
- The worker calls the shared live runtime through a thread boundary so synchronous embedding and classification do not block the FastAPI event loop.
- Semantic failures are recorded locally and never propagate into the primary ingestion retry path, so they cannot repeat InfluxDB writes or WebSocket broadcasts.
- MQTT observations update the application-owned runtime state and shared UNKNOWN pool used by review.

## Automatic UNKNOWN discovery coordination

- Discovery is requested only when successful semantic processing changes the shared UNKNOWN pool version.
- HDBSCAN runs outside the event loop through one asynchronous coordinator and one thread-worker boundary.
- Requests are debounced and coalesced without creating an unbounded number of tasks or overlapping discovery runs.
- A discovery result is published only when its pool snapshot version is still current; stale results are discarded and a fresh run is requested.
- Pending candidate replacement is atomic, and all six representation-specific discovery results remain independent without cross-view merging.
- Successfully reviewed candidate identities are suppressed from later automatic publication only for the exact representation and canonical member set.
- Discovery is enabled by default with a one-second debounce, five-second shutdown bound, and operational `min_cluster_size` default of three. These are operational defaults, not calibrated research values, and have explicit environment overrides.
- Semantic application persistence and restart recovery remain later tasks.
