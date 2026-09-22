# SmartMQTT Recommendation Architecture and Research Guide

> Canonical architecture/context document for the SmartMQTT recommendation project.
> Update this file whenever a new recommendation strategy, learning method, evidence
> provider, embedding model, feedback rule, or experiment branch is added.

## 1. Purpose of this file

This project is evolving from a single recommender into a **recommendation experimentation framework** for MQTT/IoT streams.

The long-term goal is not to hard-code three algorithms. The goal is to make it easy to add and compare:

- new evidence representations,
- new embedding models,
- new grouping/discovery strategies,
- new learning policies,
- new ranking methods,
- new feedback interpretations,
- and new evaluation protocols,

without rewriting ingestion, embedding, persistence, API, or UI logic each time.

Treat this document as the architectural source of truth for future changes.

## 2. Status vocabulary

To avoid confusing implemented behavior with planned architecture, use these labels in future notes and PRs:

- **CURRENT** — implemented in at least one active branch.
- **TARGET** — architecture we want the codebase to converge toward.
- **FUTURE** — intentionally not implemented yet; a research extension point.

Do not describe a TARGET or FUTURE capability as already working.

## 3. Repository and branch map

Primary repository:

- `https://github.com/Ariunlag/smartMqtt`

Reference/baseline branch:

- `dev-prod`

Active recommendation experiment branches:

- `experiment/recommendation-independent-evidence`
  - Independent-evidence HDBSCAN strategy.
  - Independent-evidence moving-centroid strategy.
  - Shared candidate/feedback pipeline for those two strategies.
- `experiment/recommendation-adaptive-weighted`
  - Adaptive weighted-evidence strategy.
  - Background feedback learning for evidence weights.
  - Separate adaptive persistence/editing lifecycle today.

Typical local worktrees:

```text
D:\Projects\smartMqtt\               -> dev-prod
D:\Projects\smartMqtt-independent\   -> experiment/recommendation-independent-evidence
D:\Projects\smartMqtt-adaptive\      -> experiment/recommendation-adaptive-weighted
```

Only run one Compose stack at a time because the worktrees use the same ports/container names.

## 4. Core architectural principle

The project should be a **microservice-ready modular monolith** first.

Do not immediately split every subsystem into separate network services. Instead, define module boundaries as if they could become services later.

The central rule is:

> **Evidence representation and embedding are shared infrastructure. Recommendation strategies and learners consume shared immutable evidence instead of recomputing their own embeddings.**

This keeps experiments fair and the codebase small.

### Target high-level flow

```text
MQTT messages
    |
    v
Profiling / normalization
    |
    v
Evidence providers
    |
    +--> text evidence ---------> shared embedding encoder/cache
    |
    +--> structural evidence ---> structural representation
    |
    +--> time-series evidence --> numeric/direct representation
    |
    v
Immutable EvidenceSnapshot
    |
    +----------------+----------------+----------------+
    |                |                |                |
    v                v                v                v
 HDBSCAN          Centroid        Adaptive         Future strategy
 strategy         strategy        weighted
    |                |                |
    +----------------+----------------+----------------+
                     |
                     v
              Common CandidateSet
                     |
                     v
                  API / UI
                     |
                     v
              Common feedback log
                     |
        +------------+-------------+-------------+
        |                          |             |
        v                          v             v
 HDBSCAN learner          Centroid learner   Weight learner
        |                          |             |
        +------------ learned parameters/models --+
```

## 5. Domain terminology

Use these terms consistently.

### Topic

The MQTT topic path identifying a stream, for example:

```text
chicago/lakeview/school/hvac/ahu1/temp
```

### Tag

Stable metadata describing a stream, for example:

```json
{
  "municipality": "Chicago",
  "room_type": "classroom"
}
```

### Field

Telemetry payload values/readings. Datatype is inferred from payload values; users should not manually tag a stream with labels such as `sensor=numeric`.

### Evidence space

A logically independent representation channel such as key, value, key+value, schema, topic/stream context, or time-series shape.

### Representation

The materialized data used by a strategy. A representation may be an embedding vector, structural vector, direct similarity record, time-series feature, etc.

### EvidenceSnapshot

An immutable/versioned collection of representations for a set of topics at a point in time. Strategies should consume this rather than reach back into ingestion logic.

### Strategy

A grouping/discovery algorithm. A strategy answers:

> Given evidence and parameters, what recommendation groups should be proposed?

### Learner

A feedback-driven algorithm that updates strategy parameters or a ranking model. A learner answers:

> Given feedback and historical evidence, what parameters/model should be used next?

A Strategy and Learner are separate concepts.

## 6. Evidence model

The system should support independently versioned evidence providers.

### Text-semantic evidence

Shared text encoder/embedding cache can be used by:

- `key`
- `value`
- `key_value`
- topic path / stream text
- semantic schema roles where appropriate

### Structural evidence

Schema should represent stream/message structure rather than merely grouping all numeric or string fields together.

Datatype is useful as a compatibility gate, not as dominant semantic evidence.

A future schema implementation may include:

- tag-to-tag / field-to-field compatibility,
- datatype compatibility gates,
- semantic key-role similarity,
- whole-topic structural coverage,
- unmatched/cardinality penalties.

Do not let generic tokens such as `numeric`, `string`, or `boolean` dominate schema similarity.

### Time-series evidence

Time-series shape does not need to be forced through a language embedding model.

It should remain a provider with its own numeric representation/comparator when that is more appropriate.

### Provider abstraction

TARGET:

```python
class EvidenceProvider(Protocol):
    definition: EvidenceDefinition

    def materialize(self, topic, message_or_tags, context) -> list[EvidenceRecord]:
        ...

    def compare(self, left, right) -> EvidenceComparison:
        ...
```

The provider owns its representation and comparator. The strategy consumes provider outputs.

## 7. Shared embedding infrastructure

All text-based strategies should reuse the same embedding infrastructure.

A useful cache identity is conceptually:

```text
(model_id,
 representation_type,
 representation_version,
 normalized_text)
```

Example:

```text
model_id: BAAI/bge-small-en-v1.5
representation_type: tag_value
representation_version: v2
normalized_text: Chicago
vector: [...]
```

If the embedding model or representation contract changes, old and new vectors must not silently mix.

### Why centralize embeddings

For fair research comparisons:

```text
same dataset
same normalization
same embedding model
same vectors
same feedback history
```

should be held constant while changing only:

```text
grouping strategy
learning strategy
strategy parameters
```

Otherwise algorithm differences are confounded with representation differences.

## 8. Non-negotiable evidence semantics

These rules are important for all future strategies.

1. **Key, value, key+value, schema, and stream/topic evidence are separate evidence spaces.**
2. **Tag key/value evidence must not accidentally use numeric telemetry fields as tag evidence.**
3. **Datatype is inferred from payload data.**
4. **Schema means structure, not “all numeric sensors are similar.”**
5. **A topic may belong to multiple recommendations for different reasons.**
6. **If multiple evidence spaces produce the exact same topic membership, one candidate may retain multiple reasons.**
7. **If topic membership differs by even one topic, it is a separate candidate unless a strategy explicitly defines otherwise.**
8. **Duplicate-topic canonicalization is separate from class recommendation.**
9. **Pending duplicates may still appear; confirmed duplicate aliases should not independently drive recommendations.**
10. **Explanations must reflect the evidence that actually formed or supported the recommendation; do not invent post-hoc “why” text.**

Example:

```text
KEY    -> {A,B,C}
VALUE  -> {A,B,C}
SCHEMA -> {A,B,C}

=> one candidate {A,B,C}
   reasons: key + value + schema
```

But:

```text
KEY    -> {A,B,C}
VALUE  -> {A,B}
STREAM -> {A,B,C,D}

=> three candidates
```

## 9. Strategy contract

TARGET strategy interface:

```python
class RecommendationStrategy(Protocol):
    strategy_id: str

    def discover(
        self,
        evidence: EvidenceSnapshot,
        parameters: StrategyParameters,
    ) -> CandidateSet:
        ...
```

The strategy should not:

- generate embeddings itself,
- write user feedback,
- train its learner internally,
- own UI formatting,
- mutate Saved Classes.

## 10. Current strategy families

### 10.1 Independent HDBSCAN

**CURRENT in independent experiment branch.**

Each evidence space is clustered independently.

```text
key vectors          -> HDBSCAN -> key groups
value vectors        -> HDBSCAN -> value groups
key+value vectors    -> HDBSCAN -> key+value groups
schema vectors       -> HDBSCAN -> schema groups
stream/topic vectors -> HDBSCAN -> stream groups
```

Characteristics:

- density-based,
- can mark points as noise,
- no single global semantic similarity cutoff,
- exact topic memberships from multiple channels can merge while retaining reasons.

### 10.2 Independent moving centroid

**CURRENT in independent experiment branch.**

There is no shared centroid across evidence types.

Each evidence space owns its own centroid collection:

```text
key embeddings          -> KEY centroids only
value embeddings        -> VALUE centroids only
key+value embeddings    -> KEY+VALUE centroids only
schema representation   -> SCHEMA centroids only
stream/topic embedding  -> STREAM centroids only
```

A value vector must never update a key centroid, and vice versa.

Current baseline behavior uses nearest moving-centroid assignment with a similarity threshold.

### 10.3 Adaptive weighted evidence

**CURRENT in adaptive experiment branch.**

Adaptive is conceptually different from the independent strategies.

It combines evidence channels into one weighted pair score before grouping:

```text
topic score
key score
value score
key+value score
optional series score
        |
        v
weighted combined similarity
        |
        v
grouping
```

Initial active-channel weights are equal. Missing evidence is excluded from the available-weight denominator; UI should show effective weights rather than misleading raw percentages when some channels are unavailable.

The current adaptive branch uses complete-link style grouping. A future grouping policy may use a representative/medoid/anchor if the research question favors “all members resemble one common prototype” rather than “all members resemble each other.”

Do not change that semantics silently; treat it as a strategy choice.

## 11. Strategy versus learner

This separation is central to future work.

```text
Strategy = how recommendations are formed now
Learner  = how parameters/models change from feedback
```

The same strategy may be paired with multiple learners.

Example:

```text
CentroidStrategy
  + FixedThresholdPolicy
  + ROCThresholdLearner
  + BayesianThresholdLearner
```

or:

```text
AdaptiveWeightedStrategy
  + LogisticWeightLearner
  + BayesianWeightLearner
  + RankingLearner
```

This allows research on learning without rewriting discovery.

## 12. Learner contract

TARGET:

```python
class RecommendationLearner(Protocol):
    learner_id: str

    def train(
        self,
        feedback: FeedbackDataset,
        current_parameters: dict,
    ) -> LearningResult:
        ...
```

`LearningResult` should include at least:

- proposed parameters/model,
- training data version/range,
- validation metrics,
- acceptance/rejection decision,
- previous active version,
- new version if promoted,
- reproducibility metadata.

## 13. Learning paths for the three current strategy families

### 13.1 HDBSCAN learning

**FUTURE.**

HDBSCAN parameters are not naturally learned by simple gradient updates.

A reasonable approach is validated hyperparameter search over values such as:

- `min_cluster_size`
- `min_samples`
- potentially evidence-specific parameter sets

Conceptually:

```text
feedback labels
    |
    v
candidate parameter configurations
    |
    v
re-run discovery on historical snapshots
    |
    v
score against held-out feedback
    |
    v
promote best validated configuration
```

This is likely the most expensive of the three learning paths.

### 13.2 Centroid learning

**FUTURE and comparatively simple.**

Learn evidence-specific similarity thresholds from positive and negative membership feedback.

Example:

```text
key threshold       = 0.81
value threshold     = 0.87
key+value threshold = 0.84
schema threshold    = 0.79
stream threshold    = 0.83
```

Do not collapse these into one threshold unless an experiment explicitly tests that constraint.

### 13.3 Adaptive weight learning

**CURRENT in adaptive experiment branch.**

Adaptive learns evidence weights from explicit membership feedback.

Baseline example:

```text
topic path       25%
tag key          25%
tag value        25%
tag key+value    25%
```

After validated feedback learning it may become, for example:

```text
topic path       10%
tag key          15%
tag value        55%
tag key+value    20%
```

Learning should not update from one click. It requires enough positive and negative labels across distinct contexts and must validate before activation.

The current adaptive implementation uses held-out contexts and only activates improved weights when validation beats relevant baselines/current state.

## 14. Common feedback contract

TARGET: all strategies should write to one common feedback vocabulary and preserve the exact evidence/candidate version that the user saw.

Core membership actions:

```text
KEEP / BELONGS / CONFIRM -> positive membership label
ADD_TOPIC                -> positive membership label
REMOVE_TOPIC             -> negative membership label
```

Core candidate-quality actions:

```text
USEFUL / ACCEPT_CANDIDATE -> positive candidate-quality label
NOT_USEFUL / DISMISS      -> negative candidate-quality label
```

Undo/retraction must invalidate or supersede the corresponding label rather than create contradictory training data.

Saving a recommendation as a Class may confirm selected members, but ordinary manual Class persistence should not silently fabricate recommendation-training labels unless explicitly designed to do so.

Feedback records should retain:

- strategy ID,
- learner/model version where relevant,
- candidate ID and candidate version,
- member topics,
- exact evidence snapshot or immutable reference,
- action,
- target topic when applicable,
- timestamp,
- provenance for shadow/live ranking where applicable.

## 15. Common CandidateSet target

TARGET: HDBSCAN, Centroid, Adaptive, and future strategies should return a common candidate contract.

Conceptually:

```python
CandidateSet(
    strategy=...,
    candidates=(
        Candidate(
            candidate_id=...,
            member_topics=(...),
            discovery_reasons=(...),
            evidence_support=(...),
            score_summary=...,
        ),
        ...
    ),
    available_topics=(...),
)
```

The UI should not need strategy-specific branches for normal recommendation review.

Long-term API target:

```text
GET /api/recommended-classes?strategy=independent_hdbscan
GET /api/recommended-classes?strategy=independent_centroid
GET /api/recommended-classes?strategy=adaptive_weighted
```

Today Adaptive still has a separate API/state lifecycle. Unifying this is a planned refactor, not current behavior.

## 16. Registries and extension points

TARGET registries:

```text
EvidenceProviderRegistry
EmbeddingModelRegistry
StrategyRegistry
LearnerRegistry
ModelRegistry
```

Adding a new strategy should usually require:

1. implementing the strategy interface,
2. registering the strategy,
3. adding strategy-specific config/parameters,
4. adding tests,
5. optionally registering one or more learners,
6. exposing it through the common strategy catalog.

It should not require changes throughout ingestion, persistence, UI, and embedding code.

## 17. Recommended module layout

TARGET direction:

```text
backend/services/class_recommendation/
|
+-- core/
|   +-- domain.py
|   +-- contracts.py
|   +-- snapshots.py
|   +-- feedback.py
|
+-- representation/
|   +-- profiling.py
|   +-- evidence_registry.py
|   +-- embedding.py
|   +-- cache.py
|   +-- providers/
|       +-- key.py
|       +-- value.py
|       +-- key_value.py
|       +-- schema.py
|       +-- topic.py
|       +-- series.py
|
+-- strategies/
|   +-- base.py
|   +-- hdbscan.py
|   +-- centroid.py
|   +-- adaptive_weighted.py
|
+-- learning/
|   +-- base.py
|   +-- hdbscan_parameters.py
|   +-- centroid_thresholds.py
|   +-- evidence_weights.py
|   +-- supervised_ranker.py
|
+-- registry/
|   +-- strategy_registry.py
|   +-- learner_registry.py
|   +-- model_registry.py
|
+-- application/
    +-- discovery.py
    +-- recommendation.py
    +-- feedback.py
```

This is a target organization. Do not perform a large file move solely to match the diagram unless it reduces real coupling and tests remain stable.

## 18. UI principles

The UI should explain the recommendation without exposing unnecessary research internals.

### Show

- method name,
- group members,
- concise recommendation reasons,
- meaningful semantic matches,
- effective weights when relevant,
- group/member support labels with careful wording,
- user actions: belongs/confirm, add, remove, useful/not useful, save.

### Avoid

- `centroid`, `cluster`, `shadow`, `live ranking` jargon in normal user-facing explanations unless the user explicitly opens method diagnostics,
- percentages that do not match the backend calculation,
- calling a score a probability when it is only similarity/support,
- long technical `Why?` panels that are actually post-hoc diagnostics.

For Adaptive, `Evidence` is a better label than `Why?` unless the backend exposes the exact group-forming edges/reasons.

`Topic meaning` should be called `Topic path` if the provider embeds only the MQTT path.

## 19. Evaluation discipline

Fair comparisons require controlled experiments.

Use the same:

- dataset,
- random seed,
- noise percentage,
- publisher interval,
- embedding model/version,
- evidence snapshot,
- feedback history,
- evaluation split,

when comparing strategies.

Only change the intended independent variable.

Example realistic publisher run:

```powershell
python tools\publisher\publish.py `
  --dataset tools\publisher\dataset_realistic_semantic_mix.json `
  --seed 42 `
  --noise-pct 0.03 `
  --interval 2
```

Do not use feedback from one method to evaluate another unless the experiment explicitly defines a shared-feedback protocol.

## 20. Operational safety for worktrees

Before testing latest remote changes:

```powershell
git pull --ff-only
```

Switch stacks safely:

```powershell
cd D:\Projects\smartMqtt-independent
docker compose down

cd D:\Projects\smartMqtt-adaptive
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/api/health/ready
```

Avoid `docker compose down -v` during normal switching because it deletes persistent volumes/state.

## 21. Migration roadmap

A low-risk sequence for converging the experiments into one extensible framework:

### Phase 1 — common contracts

- Define canonical `EvidenceSnapshot`.
- Define common `CandidateSet`.
- Define common feedback event schema.
- Introduce registries without changing algorithm behavior.

### Phase 2 — strategy unification

- Keep HDBSCAN and Centroid behind the same strategy registry.
- Adapt Adaptive to consume the same evidence snapshot and return the same CandidateSet.
- Move to one strategy selector/API contract.

### Phase 3 — learning unification

- Add Learner interface/registry.
- Keep Adaptive weight learner as first implementation.
- Add Centroid per-evidence threshold learner.
- Add HDBSCAN parameter learner only after evaluation criteria are stable.

### Phase 4 — optional service extraction

Only split modules into actual network microservices when there is a real need such as:

- independent scaling,
- GPU embedding service,
- separate deployment cadence,
- workload isolation,
- multi-project/shared embedding infrastructure.

The most natural first extraction is the shared representation/embedding subsystem, not individual strategies.

## 22. Things not to do

Avoid these patterns:

```text
Strategy-specific embedding pipelines
Strategy-specific copies of the same evidence data
Large if/elif chains spread across API/UI/storage
Mixing learning code directly into discovery classes
Hard-coded UI percentages
Calling time-series a text embedding requirement
Using generic datatype tokens as semantic class evidence
Changing strategy and representation simultaneously in a comparison
Silent model/vector version mixing
```

## 23. Adding a new strategy checklist

When adding a new grouping method, answer these before coding:

1. What evidence spaces does it consume?
2. Does it consume raw item vectors, topic-level vectors, pairwise scores, or all three?
3. Which representations are shared with existing strategies?
4. What parameters are fixed?
5. What parameters can be learned?
6. What constitutes one recommendation membership?
7. Can one topic belong to multiple groups?
8. When do reasons merge?
9. What feedback labels apply?
10. What evaluation metric determines improvement?
11. Can the method use the common CandidateSet and feedback contracts?
12. Does it require a new provider, or only a new strategy?

If the answer to 12 is “only a new strategy,” do not touch embedding/materialization code.

## 24. Adding a new learner checklist

1. Which strategy/parameter family does it update?
2. What labels does it consume?
3. What evidence features does it use?
4. How is train/validation leakage prevented?
5. What minimum data is required?
6. What metric determines promotion?
7. How is rollback handled?
8. Is the previous active model preserved on failure?
9. Is the model/version auditable?
10. Does training leave discovery behavior unchanged until explicit promotion/acceptance?

## 25. Research framing

The current strategy families represent different research questions:

```text
HDBSCAN
How well does density-based independent-evidence grouping work,
and can feedback improve its density parameters?

Centroid
How well does representative-center grouping work,
and can feedback learn evidence-specific semantic cutoffs?

Adaptive weighted evidence
Does learning the relative importance of evidence channels improve
recommendation quality over fixed, independent baselines?
```

Future strategies and learners should fit into the same framework so results remain comparable.

## 26. Current guiding principle

When deciding where new code belongs, use this rule:

> **Represent once, reuse everywhere. Discover with a strategy. Learn with a learner. Persist feedback centrally. Keep experiments reproducible.**

That principle should remain stable even as algorithms change.
