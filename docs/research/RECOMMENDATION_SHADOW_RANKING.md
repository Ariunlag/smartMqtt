# Recommendation shadow ranking phase

This phase measures learned recommendation decisions against real user feedback without
changing the HDBSCAN/centroid candidate set or order.

## Safety boundary

There are three separate decisions:

1. `OFFLINE_APPROVED`: the model passed an explicit offline evaluation gate.
2. `SHADOW_ACTIVE`: an operator explicitly activated that approved model for
   observational inference.
3. future `LIVE`: not implemented in this phase.

`OFFLINE_APPROVED` does not automatically enter shadow mode. `SHADOW_ACTIVE` does not
change user-facing rank. No click automatically changes any deployment state.

## Runtime flow

```text
HDBSCAN / tag-value centroid
        |
        v
persistent candidate + version + baseline rank
        |
        +-------------------------------> user-facing order (unchanged)
        |
        v
explicit SHADOW_ACTIVE model(s)
        |
        v
portable scaler + logistic inference
        |
        v
recommendation_shadow_observations
        |
        v
explicit user feedback
        |
        v
shadow_observation_id provenance link
        |
        v
shadow evaluation report
```

The shadow scorer reuses the frozen v1 training feature extractor. It does not create a
second embedding pipeline and does not fuse the independent evidence channels before
feature extraction.

Membership v1 remains anchor-relative. The anchor topic has no self-comparison feature
row, so its learned membership score is reported as unavailable with
`topic_evidence_missing`; shadow mode does not invent a synthetic score.

## Explicit deployment commands

Show current shadow state:

```powershell
python -X utf8 scripts/manage_recommendation_shadow.py --docker status
```

Activate one model that is already `OFFLINE_APPROVED`:

```powershell
python -X utf8 scripts/manage_recommendation_shadow.py --docker activate <MODEL_ID> `
  --reason "Start observational shadow evaluation"
```

Deactivate an objective without changing model registry state:

```powershell
python -X utf8 scripts/manage_recommendation_shadow.py --docker deactivate membership `
  --reason "End observational run"
```

Membership and candidate-quality models are deployed independently. Replacing one
active model records a deactivation event for the previous model and an activation event
for the new model.

## API contract

`GET /api/recommended-classes` continues returning the baseline candidates and their
baseline `rank`. A separate `shadow_evaluation` object reports:

- `ranking_effect: "none"`;
- `baseline_order_preserved: true`;
- exact active model ids/versions;
- candidate-quality probability when that objective is active;
- per-topic membership probability when extractable;
- a `shadow_run_id` and persistence status.

If there is no explicit deployment, shadow status is `unavailable` with
`no_shadow_active_models`. If shadow scoring or persistence fails, the API fails open:
the baseline recommendation response is still returned and no learned score is allowed
to reorder it.

## Exposure and feedback provenance

Every scored candidate response creates a `recommendation_shadow_observations` row with:

- candidate id and exact candidate version;
- strategy id and unchanged baseline rank;
- exact membership/candidate-quality model ids used;
- learned scores;
- scoring status and timestamp.

When feedback is recorded, the server links it to the most recent shadow observation for
the same exact candidate version. The client never supplies learned scores or model ids.

This is exposure-aware supervision. A candidate that was not shown and did not receive
explicit feedback is not a negative label.

## Evaluation

Run:

```powershell
python -X utf8 scripts/evaluate_recommendation_shadow.py --docker
```

The report groups results by exact model id/version and keeps the two objectives
separate.

Membership metrics use explicit `KEEP_TOPIC` / `REMOVE_TOPIC` labels. Candidate-quality
metrics use explicit `ACCEPT_CANDIDATE` / `DISMISS_CANDIDATE` labels. Repeated actions
for the same model/candidate-version/target use the latest explicit label.

When both labels exist, the report includes accuracy, balanced accuracy, ROC AUC, and
log loss. Candidate quality also reports mean baseline rank for positive and negative
feedback as a comparison diagnostic; the baseline rank is not converted into a fake
probability.

## What this phase proves

A successful shadow phase proves that:

- an explicitly approved model can be loaded reproducibly from its portable artifact;
- inference features match the frozen training contract;
- learned scores can be produced without changing candidate generation or rank;
- exact model/candidate exposure can be joined to later explicit feedback;
- model quality can be measured on real, exposed user decisions.

It does **not** prove that learned ranking is better merely because inference works.
Moving to live ranking requires a separate promotion/rollback contract and enough real
shadow feedback to justify the change.

## Next phase: live ranking

The final engineering phase should add an explicit live deployment state, a rollback
path to the existing strategy rank, and a comparison policy that decides whether the
learned candidate-quality/membership signals may influence ordering. Live promotion
must never be triggered directly by a feedback click.
