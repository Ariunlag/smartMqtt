# Recommendation feedback learning baseline

This document defines the first offline learning step over persistent Recommended Class
feedback. The learning layer does not regenerate embeddings and does not modify Saved
Classes, candidate membership, centroids, or live recommendation ranking.

## Source data

`recommended_class_feedback` is the factual source of labels. Every row references an
exact `candidate_id` + `candidate_version` and contains a copy of the immutable evidence
snapshot that the user saw.

The source snapshot remains richer than the first model features: it retains topic-level
channel scores, coverage, matched pair evidence, member topics, discovery evidence, and
strategy metadata. Future feature extractors can therefore be compared without asking
the user to repeat old feedback.

## Two learning objectives

Membership and candidate usefulness are different questions and must not be mixed into
one label.

### Membership

- `KEEP_TOPIC` -> positive (`1`)
- `REMOVE_TOPIC` -> negative (`0`)

The v1 membership feature vector contains:

- `key`, `value`, `key_value`, `schema`, and `stream_context` scores;
- one availability flag for each evidence id so a missing score is not confused with a
  true zero score;
- candidate coverage;
- prototype/reference coverage.

The current candidate explanation is anchor-relative and contains no self-comparison for
the anchor topic. Anchor feedback remains stored in PostgreSQL but is skipped by the v1
membership feature extractor rather than inventing synthetic features.

### Candidate quality

- `ACCEPT_CANDIDATE` -> positive (`1`)
- `DISMISS_CANDIDATE` -> negative (`0`)

The v1 candidate-quality vector aggregates the immutable per-topic evidence using mean,
minimum, and availability statistics for each evidence id, plus coverage statistics,
member count, and discovery-evidence count.

## Repeated feedback

Multiple clicks on the same exact target must not become duplicate training samples.
For one candidate version:

- membership is deduplicated by `(candidate_id, candidate_version, topic)`;
- candidate quality is deduplicated by `(candidate_id, candidate_version)`.

The latest explicit label wins. The original feedback events remain immutable in the
database for audit/history.

## Baseline model

The first baseline is:

```text
StandardScaler -> LogisticRegression
```

The purpose is not to declare Logistic Regression the final production model. It gives
an interpretable reference model and standardized coefficients that show which evidence
features are associated with positive or negative user decisions.

A model is fit only when both positive and negative labels exist. It is not promoted to
runtime ranking by this command.

## Evaluation and leakage control

Randomly splitting topics from the same candidate across train/test would overstate
performance because those rows share candidate context. Cross-validation therefore
groups by `candidate_id` using `StratifiedGroupKFold`.

Grouped cross-validation is reported only when each label occurs across at least two
candidate groups. Otherwise the model can still be fit as an exploratory baseline, but
CV metrics are reported as unavailable rather than fabricating a validation score.

When available, the report includes:

- accuracy;
- balanced accuracy;
- ROC AUC;
- log loss;
- standardized coefficients.

## Run

From the repository root with the backend environment configured for the target
PostgreSQL database:

```powershell
python -X utf8 scripts/train_recommendation_feedback.py
```

Optionally persist the JSON report outside runtime state:

```powershell
python -X utf8 scripts/train_recommendation_feedback.py --output artifacts/recommendation-learning.json
```

The command reads feedback, fits models in memory, prints the report, and exits. It does
not save/promote a model or alter recommendation state.

## Next evaluation step

Once enough feedback exists, compare at least:

1. HDBSCAN candidate generation alone;
2. tag-value centroid candidate generation alone;
3. evidence-weighted/ranked output using the learned membership signal;
4. candidate-quality ranking using the separate quality model.

Promotion into live ranking should happen only after an explicit offline evaluation and
model-version/promotion contract are defined.
