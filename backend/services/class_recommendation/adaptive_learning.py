"""Small constrained model fitted to explicit, pre-edit membership evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, softmax

from .adaptive_evidence import weighted_score


def baseline(ids, manifest_id):
    return {"version": 0, "manifest_id": manifest_id, "weights": {k: 1 / len(ids) for k in ids},
            "bias": -4., "scale": 8., "status": "baseline", "trained_sequence": 0,
            "sample_count": 0, "updated_at": None}


def effective_labels(events, manifest_id):
    retracted = {event["details"].get("undo_event") for event in events if event["action"] == "UNDO"}
    latest = {}
    for event in events:
        if event["event_id"] in retracted or event.get("label") is None:
            continue
        # Fixture events remain factual records but are excluded from real adaptation.
        if event["details"].get("fixture") or event["details"].get("manifest_id") != manifest_id:
            continue
        latest[(event["group_id"], event["topic"])] = event
    return [e for e in sorted(latest.values(), key=lambda e: e["sequence"]) if any(v.get("status") == "available"
                                             for v in e["evidence"].values())]


def _arrays(events, ids):
    values, masks = [], []
    for event in events:
        values.append([event["evidence"].get(k, {}).get("score") or 0. for k in ids])
        masks.append([float(event["evidence"].get(k, {}).get("status") == "available") for k in ids])
        for i, k in enumerate(ids):
            values[-1][i] *= event["evidence"].get(k, {}).get("coverage", 1.)
    return np.asarray(values), np.asarray(masks), np.asarray([e["label"] for e in events])


def _fit(events, ids, regularization):
    x, mask, y = _arrays(events, ids)
    # Equal total mass per context, so a large manually selected Class cannot dominate.
    counts = Counter(e["group_id"] for e in events)
    sample_weights = np.asarray([1 / counts[e["group_id"]] for e in events])
    sample_weights /= sample_weights.sum()

    def loss(theta):
        weights = softmax(theta[:len(ids)])
        denominator = mask @ weights
        scores = (x * mask) @ weights / np.maximum(denominator, 1e-12)
        logits = theta[-2] + np.exp(theta[-1]) * scores
        return float(np.sum(sample_weights * (np.logaddexp(0, logits) - y * logits))
                     + regularization * np.sum((weights - 1 / len(ids)) ** 2))

    initial = np.r_[np.zeros(len(ids)), -4., np.log(8.)]
    result = minimize(loss, initial, method="L-BFGS-B",
                      bounds=[(-8, 8)] * len(ids) + [(-20, 20), (-2, 4)])
    if not result.success or not np.isfinite(result.fun):
        return None
    return {"weights": dict(zip(ids, softmax(result.x[:len(ids)]).tolist(), strict=True)),
            "bias": float(result.x[-2]), "scale": float(np.exp(result.x[-1]))}


def log_loss(model, events):
    losses = []
    for event in events:
        score = weighted_score(event["evidence"], model["weights"])
        if score is not None:
            p = float(np.clip(expit(model["bias"] + model["scale"] * score), 1e-8, 1-1e-8))
            losses.append(-event["label"] * np.log(p) - (1-event["label"]) * np.log(1-p))
    return float(np.mean(losses)) if losses else float("inf")


def train(events, ids, manifest_id, current, *, min_labels=12, regularization=.1):
    labels = effective_labels(events, manifest_id)
    sequence = max((e["sequence"] for e in events), default=0)
    if sequence <= current.get("trained_sequence", 0):
        return None
    if len(labels) < min_labels or {e["label"] for e in labels} != {0, 1}:
        return None
    # Hold out complete contexts first seen later. Related revisions never straddle folds.
    groups = list(dict.fromkeys(e["group_id"] for e in labels))
    if len(groups) < 4:
        return None
    held_out = set(groups[max(2, int(len(groups)*.75)):])
    training = [e for e in labels if e["group_id"] not in held_out]
    validation = [e for e in labels if e["group_id"] in held_out]
    cutoff = min(e["sequence"] for e in validation)
    training = [e for e in training if e["sequence"] < cutoff]
    # Purge shared devices from training to reduce related-topic leakage.
    held_topics = {topic for e in validation for topic in
                   [e["topic"], *e["details"].get("reference_topics", [])]}
    training = [e for e in training if not held_topics.intersection(
        [e["topic"], *e["details"].get("reference_topics", [])])]
    if {e["label"] for e in training} != {0, 1} or {e["label"] for e in validation} != {0, 1}:
        return None
    candidate = _fit(training, ids, regularization)
    if candidate is None:
        return None
    reference = baseline(ids, manifest_id)
    report = {"candidate_loss": log_loss(candidate, validation),
              "baseline_loss": log_loss(reference, validation),
              "active_loss": log_loss(current, validation),
              "training_count": len(training), "validation_count": len(validation),
              "policy": "group-held-out-topic-purged-v1"}
    improved = report["candidate_loss"] < min(report["baseline_loss"], report["active_loss"]) - 1e-4
    # Persist the attempt cursor even on rejection; preserve active weights/version semantics.
    return {**current, **(candidate if improved else {}), "manifest_id": manifest_id,
            "status": "learned" if improved else current["status"],
            "sample_count": len(labels), "trained_sequence": sequence,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "evaluation": report, "last_update_accepted": improved}
