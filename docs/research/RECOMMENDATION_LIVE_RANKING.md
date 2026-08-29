# Recommendation live ranking and rollback contract

This phase is the first place where a learned recommendation model may change the order
shown to users. The scope is intentionally narrow and reversible.

## Live v1 scope

Live v1 uses only the `candidate_quality` objective. HDBSCAN or the tag-value centroid
strategy still generates the exact candidate groups. The learned model may reorder those
existing groups, but it does not:

- add or remove candidate members;
- create a new candidate;
- alter pair/stream embeddings;
- mutate Saved Classes;
- use membership feedback to silently delete topics;
- treat candidates that were not shown as negative labels.

Membership learning remains shadow/evaluation-only until a separate membership policy is
designed and validated.

## Ranking policy

When no live deployment exists, the baseline discovery order is returned unchanged.

When a live candidate-quality model is active, each exact persisted candidate version is
converted to the same `candidate-quality-evidence-v1` feature vector used during training
and shadow scoring. The portable registry artifact computes the probability. Ordering is:

```text
candidate_quality_score DESC
baseline_rank ASC
candidate_id ASC
```

Baseline rank is therefore the deterministic tie-breaker.

## Promotion gate

There is no force/bypass flag. A model must be `OFFLINE_APPROVED` and must have explicit
real-feedback shadow evaluation for that exact model id. The default `live-shadow-gate-v1`
prototype policy requires:

- at least 20 shadow-labeled candidate-quality samples;
- at least 5 positive labels;
- at least 5 negative labels;
- at least 10 distinct candidate versions;
- balanced accuracy >= 0.60;
- ROC AUC >= 0.60;
- at least 10 positive-vs-negative pairwise comparisons;
- learned pairwise ordering must be no worse than baseline (`delta >= 0.0`);
- fixture feedback remains excluded;
- the shadow report must use explicit feedback only;
- unshown candidates must not be treated as negatives;
- rank counterfactuals must use the same-shadow-run comparison policy.

These values are explicit prototype deployment policy, not a claim that 20 labels are
scientifically sufficient for every deployment.

### Same-run pairwise comparison

Rank numbers are only meaningful inside one candidate set. Therefore positive/negative
pairwise ordering is compared only when both feedback events refer to observations from
the same `shadow_run_id`. Rank 1 from one request is never compared to rank 3 from an
unrelated request.

The learned score can still be evaluated globally with balanced accuracy/ROC AUC because
the score itself is on one model probability scale; the rank counterfactual is run-local.

## Commands

Use the Compose-native wrapper from the repository root.

Check whether a candidate-quality model can go live:

```powershell
python -X utf8 scripts/manage_recommendation_live.py --docker check <model_id>
```

Activate only after the gate passes:

```powershell
python -X utf8 scripts/manage_recommendation_live.py --docker activate \
  <model_id> --reason "Shadow evaluation passed live gate"
```

Inspect deployment state:

```powershell
python -X utf8 scripts/manage_recommendation_live.py --docker status
```

Immediately restore baseline order:

```powershell
python -X utf8 scripts/manage_recommendation_live.py --docker rollback \
  --reason "Rollback after live evaluation"
```

There is intentionally no CLI option that ignores a failed promotion gate.

## Request-time safety

Live inference fails closed to the baseline order for the whole request. The service does
not partially reorder a candidate list when one candidate cannot be scored.

Baseline fallback occurs when:

- no live deployment exists;
- the deployed model is no longer `OFFLINE_APPROVED`;
- the registry artifact/feature contract is incompatible;
- an exact candidate snapshot is missing;
- candidate-quality features cannot be reconstructed;
- live exposure persistence fails;
- an unexpected live-ranking exception reaches the API boundary.

The API exposes `live_ranking` metadata so the caller can distinguish `baseline`,
`applied`, and `fallback` behavior.

## Exposure provenance

Every successfully live-ranked response persists an observation per candidate with:

- one request-level `live_run_id`;
- candidate id/version;
- strategy id;
- baseline rank;
- live rank;
- exact model id;
- candidate-quality score.

The UI keeps the run id from the same response that produced the displayed cards and
returns it with later feedback. The backend resolves exactly
`(live_run_id, candidate_id, candidate_version)` before storing the nullable
`live_observation_id`. It does not look up the latest candidate observation, because a
background or manual refresh could have created a newer exposure after the one the user
actually judged.

Shadow attribution follows the same pattern with `shadow_run_id`. If a legacy client
omits a run id, or an exact observation can no longer be resolved, the user feedback is
still stored and the observational link remains `NULL`; provenance must never block the
label itself. The immutable candidate evidence snapshot remains the learning source of
truth.

Both shadow and live observation foreign keys use `ON DELETE SET NULL`, allowing
observational history cleanup without deleting feedback labels.

## Live post-evaluation

Evaluate live exposures with:

```powershell
python -X utf8 scripts/evaluate_recommendation_live.py --docker
```

The report:

- excludes `acceptance/` fixture feedback by default;
- uses only explicit candidate-quality actions;
- never invents negatives for unshown candidates;
- applies latest-label-wins per model/candidate-version;
- reports probability classification metrics;
- compares live rank with baseline rank only within the same `live_run_id`.

This report is observational evidence for keeping or rolling back a live deployment. It
does not automatically mutate embeddings, feedback, or model coefficients.

## Completion boundary

With this phase merged, the engineering path from evidence to reversible learned ranking
is complete:

```text
independent evidence
  -> HDBSCAN / centroid candidate generation
  -> immutable candidate versions
  -> explicit feedback
  -> offline learning
  -> model registry + offline gate
  -> explicit shadow deployment
  -> shadow-vs-feedback evaluation
  -> gated live candidate reordering
  -> live exposure evaluation
  -> immediate baseline rollback
```

What remains after engineering completion is empirical validation: collecting enough real
user feedback for a model to pass offline and shadow gates, deciding whether to activate
it, then monitoring live behavior. A lack of real labels is not bypassed with acceptance
fixtures or synthetic negatives.
