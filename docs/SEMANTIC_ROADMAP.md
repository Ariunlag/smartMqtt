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
Equal-view multi-view consensus
        |
        v
KNOWN / UNCERTAIN / UNKNOWN decision policy
        |
        v
        +--> KNOWN / UNCERTAIN
        |
        +--> UNKNOWN
                 |
                 v
          UNKNOWN stream pool
                 |
                 v
          Representation-specific HDBSCAN candidate discovery
        |
        v
Explicit candidate confirmation / rejection
        |
        v
Trusted representation-specific prototype update
        |
        v
Six-view completeness check
        |
        +--> incomplete -> retain evidence
        |
        v
RepresentationClassCentroids
        |
        v
Existing known-class scoring
        |
        v
Representation reliability learning
```

Only the foundation stages identified as completed below currently exist.
Automatic builder invocation, embedding refresh integration, feedback, and
reliability learning remain planned stages.

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
- [x] Multi-view consensus
- [x] KNOWN / UNCERTAIN / UNKNOWN decision policy
- [x] UNKNOWN stream pool
- [x] HDBSCAN candidate-class discovery foundation
- [x] Human/system confirmation flow foundation
- [x] Trusted feedback-driven representation prototype updates
- [x] Full six-view known-class assembly from trusted evidence
- [x] Controlled semantic benchmark foundation
- [x] Semantic experiment runner
- [x] Initial known/open-world evaluation metrics
- [x] Threshold calibration protocol
- [x] Frozen-config benchmark execution
- [x] Recorded semantic calibration Pareto-frontier artifact and report
- [x] Editable candidate membership review
- [x] Positive/negative member feedback evidence
- [x] Apply positive reviewed membership to six-view class prototypes
- [x] Safe prototype reconciliation after edited membership feedback
- [x] Negative membership constraints
- [x] Integrated semantic feedback application workflow
- [x] Reviewed prototype synchronization into the live known-class registry
- [x] Negative-constraint filtering during runtime candidate eligibility
- [x] Production MQTT semantic sidecar
- [x] Bounded isolated semantic processing queue
- [x] Shared live runtime processing from MQTT observations
- [x] Automatic UNKNOWN-pool discovery trigger
- [x] Debounced and stale-safe HDBSCAN execution
- [x] Automatic publication of pending review candidates

The semantic runtime now consumes MQTT observations through an isolated,
bounded sidecar after the existing primary handlers. It updates the shared
in-memory runtime and UNKNOWN pool without blocking or retrying the primary
InfluxDB/WebSocket pipeline. Discovery scheduling and durable PostgreSQL
snapshot recovery are now application-owned services.

### Planned work

- [x] Candidate-review backend API
- [x] Candidate-review React MVP
- [x] End-to-end semantic review workflow test
- [x] Shared semantic application composition
- [x] Shared UNKNOWN pool between processing and review
- [x] Shared prototype and constraint state for review workflow
- [x] Synchronize reviewed prototypes into the known-class registry
- [x] Apply negative constraints during runtime candidate eligibility
- [x] Wire SemanticRuntime into production MQTT ingestion
- [x] Trigger UNKNOWN discovery from shared pool
- [x] Publish pending discovery candidates to review runtime
- [x] Durable semantic application snapshot
- [x] PostgreSQL semantic-state repository
- [x] Startup restore before semantic processing
- [x] Bounded debounced persistence writer
- [x] Restart recovery integration test
- [x] Operational semantic diagnostics UI
- [ ] Full real-broker acceptance test
- [ ] Multi-instance semantic ownership strategy
- [ ] Snapshot retention and historical audit
- [ ] Representation reliability experiments
- [ ] Versioned adaptive recalibration
- [ ] Expanded hard benchmark and final TEST report
- [ ] Semantic benchmark experiment runner and metrics
- [ ] Threshold calibration protocol
- [ ] Frozen-config benchmark execution
- [ ] HDBSCAN discovery evaluation
- [ ] Full benchmark result report
- [ ] Feedback-driven online class updates
- [ ] Representation reliability learning
- [ ] Multi-prototype semantic classes
- [ ] Research/diagnostic backend API
- [ ] Research/diagnostic React UI

## Research and evaluation

The controlled semantic benchmark foundation supplies deterministic structured
stream scenarios and explicit known/unseen ground truth for later evaluation.
It does not run semantic services or calculate metrics. Planned experiments
will compare static single-representation and six-view baselines with
temporal/stability-aware and full open-world workflows. Metrics and an
experiment runner remain planned.

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
- HDBSCAN provides representation-specific candidate discovery for UNKNOWN
  streams; semantic class creation remains planned.

The UNKNOWN stream pool retains the latest UNKNOWN evidence in memory.
Representation-specific HDBSCAN discovery now exposes candidate structure and
noise independently for all six views. Candidate clusters are not semantic
classes. Explicit HUMAN or SYSTEM confirmation/rejection records trusted
feedback without creating or updating classes; class updates and the remaining
UNKNOWN workflow are still planned.

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
    -> embedding refresh through the ordered MQTT semantic sidecar
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
`TemporalStreamProfile`. The application-owned MQTT sidecar now invokes this
runtime workflow without changing the primary ingestion pipeline.

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
for every representation-by-class pair.

The equal-view consensus baseline preserves the six view winners and summarizes
each class with its top-1 vote count, mean rank, and unweighted mean similarity.
It ranks classes lexicographically by votes descending, mean rank ascending,
mean similarity descending, and class ID ascending. Exact per-view score ties
use class ID ordering only for reproducibility. The consensus engine produces
no weighted score and makes no class acceptance/rejection decision itself.

The open-world decision policy applies explicitly configured vote, absolute
similarity, and top-versus-runner-up similarity-margin thresholds. `UNKNOWN`
represents no known classes or clearly weak absolute evidence; `KNOWN` requires
all configured acceptance criteria; `UNCERTAIN` preserves the middle or
ambiguous region. Thresholds have no built-in recommended values and require
later empirical calibration. The policy does not populate an UNKNOWN pool or
assign classes in the production path.

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

## Real-stack operational acceptance

The repository contains a bounded, non-destructive acceptance runner for the
existing Docker Compose architecture. It verifies migration, API subscription,
Mosquitto publication, InfluxDB ingestion, semantic processing/discovery/review,
restart recovery, broker recovery, PostgreSQL persistence recovery, queue
backpressure, and final shutdown flush paths. The runner uses unique per-run
topic and persistence namespaces and never deletes volumes.

Operational verification uses two additive vector-free endpoints: one reports
topic decision metadata and one requests a coalesced persistence retry after a
repository outage. Neither endpoint changes semantic scoring or threshold
behavior. See `docs/REAL_STACK_ACCEPTANCE.md` for the command and runbook.

Real-broker acceptance completed on 2026-07-31 with run ID
`codex-20260731`. All phases passed against the real Compose stack. The reviewed
follow-up stream remained `UNCERTAIN` under the frozen strict policy because
its mean similarity was below the unchanged known-class threshold; no threshold
was weakened. The bounded burst published 80 messages, accepted and processed
3, dropped 77 explicitly, and recorded no semantic failures. Final persisted
generation 15 was restored after a 3.5-second bounded shutdown.

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
