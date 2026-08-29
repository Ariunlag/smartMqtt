# Recommendation model registry and promotion contract

This document defines the lifecycle for learned recommendation models after feedback has
been converted into the fixed offline learning datasets.

The registry is intentionally disconnected from live recommendation ranking. A model can
be registered and approved offline without changing HDBSCAN, tag-value centroid, Saved
Classes, embeddings, or the order shown to users.

## Model artifact

Each trainable objective produces a portable JSON artifact rather than a Python pickle.
The artifact records:

- objective (`membership` or `candidate_quality`);
- feature-contract version and ordered feature names;
- deterministic semantic dataset fingerprint;
- source feedback ids for audit;
- StandardScaler mean, scale, and variance;
- Logistic Regression classes, coefficients, intercept, solver, and training settings.

The database assigns an independent monotonic `model_version` per objective. The same
objective + feature contract + semantic dataset + model type is deduplicated instead of
creating another version for repeated clicks that do not change the effective training
examples.

## Evaluation is separate from artifact identity

An artifact is immutable. Evaluation policy can change later, so gate results are stored
in `recommendation_model_evaluations` rather than embedded into the model row.

The initial policy is `offline-gate-v1`. Its default prototype thresholds are:

- at least 20 real training samples;
- at least 5 positive labels;
- at least 5 negative labels;
- at least 4 distinct strategy-independent member-set evaluation groups;
- grouped cross-validation must be available;
- balanced accuracy >= 0.60;
- ROC AUC >= 0.60;
- fixture feedback must remain excluded.

These numbers are an explicit engineering policy for deciding when a prototype is worth
advancing. They are not claims of statistical sufficiency or final product thresholds.
The CLI can run the same model against another explicit threshold set; each policy is
fingerprinted and stored as a separate evaluation.

## Status lifecycle

```text
feedback snapshots
      |
      v
CANDIDATE model artifact
      |
      v
EVALUATED (one or more immutable gate reports)
      |
      | explicit human command + passing evaluation
      v
OFFLINE_APPROVED
      |
      | superseded or explicitly retired
      v
RETIRED
```

`OFFLINE_APPROVED` means only that the artifact passed the selected offline gate and was
explicitly selected for a possible next experiment. Approval itself has **no runtime
ranking effect** and does not automatically activate inference.

Only one `OFFLINE_APPROVED` model can exist per objective. Approving a newer model retires
the previously approved model for that objective and records both lifecycle events.

## Tables

`recommendation_model_versions` stores immutable artifact/version identity and training
report.

`recommendation_model_evaluations` stores gate-policy fingerprints and immutable gate
reports for a model.

`recommendation_model_events` stores `REGISTERED`, `EVALUATED`, `OFFLINE_APPROVED`, and
`RETIRED` lifecycle events.

Shadow deployment state is deliberately stored in separate tables. The runtime scorer
only consumes a model when it is both `OFFLINE_APPROVED` and explicitly present in
`recommendation_shadow_deployments`.

## Commands

The normal Compose topology keeps PostgreSQL inside the Docker network, so use the Docker
wrapper from the repository root.

Register current real-feedback models and evaluate them with the default gate:

```powershell
python -X utf8 scripts/manage_recommendation_models.py --docker register
```

List model versions:

```powershell
python -X utf8 scripts/manage_recommendation_models.py --docker list
```

Inspect one model and all of its evaluations:

```powershell
python -X utf8 scripts/manage_recommendation_models.py --docker show <model_id>
```

After a gate has passed, explicitly approve the model for offline/shadow experimentation:

```powershell
python -X utf8 scripts/manage_recommendation_models.py --docker approve-offline \
  <model_id> <evaluation_id> --reason "Selected after grouped offline evaluation"
```

Retire a model:

```powershell
python -X utf8 scripts/manage_recommendation_models.py --docker retire \
  <model_id> --reason "Superseded by a later experiment"
```

Fixture-inclusive registration exists only for controlled smoke testing and cannot pass
the default source-policy gate:

```powershell
python -X utf8 scripts/manage_recommendation_models.py --docker register \
  --include-fixture-feedback
```

## What comes after offline approval

Shadow inference is a separate explicit deployment decision. `OFFLINE_APPROVED` does not
imply `SHADOW_ACTIVE`.

Activate an approved model only when a shadow experiment is intentionally starting:

```powershell
python -X utf8 scripts/manage_recommendation_shadow.py --docker activate \
  <model_id> --reason "Start observational shadow evaluation"
```

The shadow scorer records learned membership/candidate-quality probabilities beside the
existing baseline rank, but it never reorders candidates. See
`docs/research/RECOMMENDATION_SHADOW_RANKING.md` for the exposure-provenance and
evaluation contract.

A future live-ranking phase must add a separate explicit promotion and rollback contract.
Neither offline approval nor shadow activation is production ranking deployment.
