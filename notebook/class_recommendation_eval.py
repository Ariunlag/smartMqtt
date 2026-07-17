"""Reproducible evaluation helpers for MQTT class recommendation experiments.

The module deliberately separates two questions:

1. How should a whole payload be represented as one text embedding?
2. How should separately embedded key/value pairs be combined and matched?

Evaluation is class recommendation, not clustering.  Each vendor is held out in
turn, class representations are built only from the remaining vendors, and the
held-out streams are ranked against the known classes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import accuracy_score, f1_score


NOTEBOOK_DIR = Path(__file__).resolve().parent
DEFAULT_PAYLOAD_PATH = NOTEBOOK_DIR / "payloads_dataset.json"
DEFAULT_METADATA_PATH = NOTEBOOK_DIR / "smartmqtt_flat_metadata.csv"
DEFAULT_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def is_numeric_value(value) -> bool:
    """Treat JSON booleans as categories, not numeric measurements."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clean_text(value) -> str:
    return str(value).strip().lower().replace("_", " ").replace("-", " ")


def value_to_text(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return clean_text(value)


def l2_normalize(matrix: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim == 1:
        norm = max(float(np.linalg.norm(matrix)), eps)
        return matrix / norm
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, eps)


def load_dataset(
    payload_path: Path = DEFAULT_PAYLOAD_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
) -> pd.DataFrame:
    with payload_path.open("r", encoding="utf-8") as handle:
        messages = json.load(handle)

    payload_df = pd.DataFrame(messages)
    metadata_df = pd.read_csv(metadata_path)

    required_payload_columns = {"topic", "payload"}
    required_metadata_columns = {"topic", "true_class", "manufacturer"}
    if not required_payload_columns.issubset(payload_df.columns):
        raise ValueError(
            f"Payload data must contain {sorted(required_payload_columns)}"
        )
    if not required_metadata_columns.issubset(metadata_df.columns):
        raise ValueError(
            f"Metadata must contain {sorted(required_metadata_columns)}"
        )
    if payload_df["topic"].duplicated().any():
        duplicates = payload_df.loc[payload_df["topic"].duplicated(), "topic"].tolist()
        raise ValueError(f"Duplicate payload topics: {duplicates}")
    if metadata_df["topic"].duplicated().any():
        duplicates = metadata_df.loc[
            metadata_df["topic"].duplicated(), "topic"
        ].tolist()
        raise ValueError(f"Duplicate metadata topics: {duplicates}")
    if not payload_df["payload"].map(lambda item: isinstance(item, dict)).all():
        raise ValueError("Every payload must be a JSON object")

    payload_topics = set(payload_df["topic"])
    metadata_topics = set(metadata_df["topic"])
    if payload_topics != metadata_topics:
        raise ValueError(
            "Payload/metadata topic mismatch: "
            f"missing_metadata={sorted(payload_topics - metadata_topics)}, "
            f"missing_payload={sorted(metadata_topics - payload_topics)}"
        )

    data = payload_df.merge(
        metadata_df[["topic", "true_class", "manufacturer", "notes"]],
        on="topic",
        how="inner",
        validate="one_to_one",
    )
    if data[["true_class", "manufacturer"]].isna().any().any():
        raise ValueError("Every stream needs true_class and manufacturer labels")

    # Vendor-held-out evaluation requires every class to remain represented after
    # any one vendor is removed.
    vendor_counts = (
        data.groupby(["true_class", "manufacturer"]).size().unstack(fill_value=0)
    )
    for class_name, row in vendor_counts.iterrows():
        if int((row > 0).sum()) < 2:
            raise ValueError(
                f"Class {class_name!r} occurs under fewer than two manufacturers"
            )

    return data.reset_index(drop=True)


def dataset_summary(data: pd.DataFrame) -> pd.DataFrame:
    return (
        data.groupby("true_class")
        .agg(
            streams=("topic", "size"),
            manufacturers=("manufacturer", "nunique"),
            min_fields=("payload", lambda rows: min(len(row) for row in rows)),
            max_fields=("payload", lambda rows: max(len(row) for row in rows)),
        )
        .sort_index()
        .reset_index()
    )


def make_flat_representations(payload: dict) -> dict[str, str]:
    keys = [clean_text(key) for key in payload]
    values = [value_to_text(value) for value in payload.values()]
    key_values = [
        f"{clean_text(key)}: {value_to_text(value)}"
        for key, value in payload.items()
    ]
    numeric_key_only = [
        clean_text(key)
        if is_numeric_value(value)
        else f"{clean_text(key)}: {value_to_text(value)}"
        for key, value in payload.items()
    ]
    field_schema = [
        f"{clean_text(key)}: {'numeric' if is_numeric_value(value) else 'categorical'}"
        for key, value in payload.items()
    ]
    return {
        "flat_value_only": " | ".join(values),
        "flat_key_only": " | ".join(keys),
        "flat_key_value": " | ".join(key_values),
        "flat_numeric_key_only": " | ".join(numeric_key_only),
        "flat_field_schema": " | ".join(field_schema),
    }


def build_flat_texts(data: pd.DataFrame) -> dict[str, list[str]]:
    rows = [make_flat_representations(payload) for payload in data["payload"]]
    names = list(rows[0])
    return {name: [row[name] for row in rows] for name in names}


def build_pair_table(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for stream_index, row in data.iterrows():
        for key, value in row["payload"].items():
            key_text = clean_text(key)
            value_text = value_to_text(value)
            numeric = is_numeric_value(value)
            rows.append(
                {
                    "stream_index": stream_index,
                    "topic": row["topic"],
                    "key": str(key),
                    "value": value,
                    "is_numeric": numeric,
                    "key_text": key_text,
                    "value_text": value_text,
                    "key_value_text": f"{key_text}: {value_text}",
                    "key_value_without_numeric_text": (
                        key_text if numeric else f"{key_text}: {value_text}"
                    ),
                }
            )
    return pd.DataFrame(rows)


def load_model(model_name: str = DEFAULT_MODEL):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def encode(model, texts: Iterable[str]) -> np.ndarray:
    return np.asarray(
        model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        ),
        dtype=float,
    )


def rank_metrics(
    true_labels: list[str],
    predicted_labels: list[str],
    ranked_labels: list[list[str]],
) -> dict[str, float]:
    reciprocal_ranks = [
        1.0 / (ranking.index(truth) + 1)
        for truth, ranking in zip(true_labels, ranked_labels)
    ]
    return {
        "top1_accuracy": float(accuracy_score(true_labels, predicted_labels)),
        "macro_f1": float(
            f1_score(true_labels, predicted_labels, average="macro", zero_division=0)
        ),
        "recall_at_3": float(
            np.mean(
                [
                    truth in ranking[:3]
                    for truth, ranking in zip(true_labels, ranked_labels)
                ]
            )
        ),
        "mrr": float(np.mean(reciprocal_ranks)),
    }


def evaluate_vector_recommendations(
    matrix: np.ndarray,
    data: pd.DataFrame,
    method: str,
) -> tuple[dict[str, float], pd.DataFrame]:
    """Recommend classes from class-centroid cosine similarity.

    A stream's entire manufacturer is excluded while that stream is evaluated.
    This makes the test harder and avoids learning a vendor naming template that
    also appears in the test stream.
    """
    matrix = l2_normalize(matrix)
    labels = data["true_class"].tolist()
    vendors = data["manufacturer"].tolist()
    classes = sorted(set(labels))
    predictions: list[str] = []
    rankings: list[list[str]] = []
    cases: list[dict] = []

    for query_index, query in enumerate(matrix):
        train_indices = [
            index
            for index, vendor in enumerate(vendors)
            if vendor != vendors[query_index]
        ]
        scores: dict[str, float] = {}
        for class_name in classes:
            class_indices = [
                index
                for index in train_indices
                if labels[index] == class_name
            ]
            if not class_indices:
                scores[class_name] = float("-inf")
                continue
            prototype = l2_normalize(matrix[class_indices].mean(axis=0))
            scores[class_name] = float(query @ prototype)

        ranking = sorted(classes, key=scores.get, reverse=True)
        prediction = ranking[0]
        truth = labels[query_index]
        predictions.append(prediction)
        rankings.append(ranking)
        cases.append(
            {
                "method": method,
                "topic": data.iloc[query_index]["topic"],
                "manufacturer": vendors[query_index],
                "true_class": truth,
                "predicted_class": prediction,
                "true_rank": ranking.index(truth) + 1,
                "top_score": scores[prediction],
                "true_score": scores[truth],
                "correct": prediction == truth,
            }
        )

    metrics = {"method": method, **rank_metrics(labels, predictions, rankings)}
    return metrics, pd.DataFrame(cases)


def optimal_pair_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """One-to-one pair matching with a penalty for unmatched fields.

    The old symmetric-best-match approach allowed many unrelated fields to use
    the same generic field as their best match.  Hungarian assignment prevents
    that many-to-one inflation.  Dividing by the larger set size gives unmatched
    fields a zero contribution.
    """
    similarities = np.asarray(left) @ np.asarray(right).T
    left_indices, right_indices = linear_sum_assignment(
        similarities,
        maximize=True,
    )
    matched = similarities[left_indices, right_indices].sum()
    return float(matched / max(len(left), len(right)))


def build_stream_similarity_matrix(
    pair_matrix: np.ndarray,
    pairs: pd.DataFrame,
    stream_count: int,
) -> np.ndarray:
    stream_pair_indices = {
        stream_index: pairs.index[
            pairs["stream_index"] == stream_index
        ].to_numpy()
        for stream_index in range(stream_count)
    }
    similarities = np.eye(stream_count, dtype=float)
    for left_index in range(stream_count):
        left = pair_matrix[stream_pair_indices[left_index]]
        for right_index in range(left_index + 1, stream_count):
            right = pair_matrix[stream_pair_indices[right_index]]
            score = optimal_pair_similarity(left, right)
            similarities[left_index, right_index] = score
            similarities[right_index, left_index] = score
    return similarities


def evaluate_similarity_recommendations(
    similarities: np.ndarray,
    data: pd.DataFrame,
    method: str,
) -> tuple[dict[str, float], pd.DataFrame]:
    labels = data["true_class"].tolist()
    vendors = data["manufacturer"].tolist()
    classes = sorted(set(labels))
    predictions: list[str] = []
    rankings: list[list[str]] = []
    cases: list[dict] = []

    for query_index in range(len(data)):
        scores: dict[str, float] = {}
        for class_name in classes:
            class_indices = [
                index
                for index in range(len(data))
                if index != query_index
                and vendors[index] != vendors[query_index]
                and labels[index] == class_name
            ]
            scores[class_name] = (
                float(similarities[query_index, class_indices].mean())
                if class_indices
                else float("-inf")
            )

        ranking = sorted(classes, key=scores.get, reverse=True)
        prediction = ranking[0]
        truth = labels[query_index]
        predictions.append(prediction)
        rankings.append(ranking)
        cases.append(
            {
                "method": method,
                "topic": data.iloc[query_index]["topic"],
                "manufacturer": vendors[query_index],
                "true_class": truth,
                "predicted_class": prediction,
                "true_rank": ranking.index(truth) + 1,
                "top_score": scores[prediction],
                "true_score": scores[truth],
                "correct": prediction == truth,
            }
        )

    metrics = {"method": method, **rank_metrics(labels, predictions, rankings)}
    return metrics, pd.DataFrame(cases)


def run_flat_experiment(
    data: pd.DataFrame,
    model,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    metric_rows: list[dict] = []
    case_frames: list[pd.DataFrame] = []
    for method, texts in build_flat_texts(data).items():
        matrix = encode(model, texts)
        metrics, cases = evaluate_vector_recommendations(matrix, data, method)
        metric_rows.append(metrics)
        case_frames.append(cases)
    return (
        pd.DataFrame(metric_rows).sort_values(
            ["macro_f1", "top1_accuracy"],
            ascending=False,
        ),
        pd.concat(case_frames, ignore_index=True),
    )


def run_pair_experiment(
    data: pd.DataFrame,
    model,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = build_pair_table(data)
    key_matrix = encode(model, pairs["key_text"])
    value_matrix = encode(model, pairs["value_text"])

    methods: dict[str, np.ndarray] = {
        "pair_value_only": value_matrix,
        "pair_key_only": key_matrix,
        "pair_key_value": encode(model, pairs["key_value_text"]),
        "pair_key_value_without_numeric": encode(
            model,
            pairs["key_value_without_numeric_text"],
        ),
    }

    for key_weight in (0.0, 0.25, 0.5, 0.75, 1.0):
        name = f"weighted_key_{key_weight:.2f}_value_{1-key_weight:.2f}"
        methods[name] = l2_normalize(
            key_weight * key_matrix + (1.0 - key_weight) * value_matrix
        )

    numeric_mask = pairs["is_numeric"].to_numpy()
    for numeric_value_weight in (0.0, 0.1, 0.25, 0.5):
        categorical_value_weight = 0.5
        value_weights = np.where(
            numeric_mask,
            numeric_value_weight,
            categorical_value_weight,
        )[:, None]
        name = f"numeric_aware_numvalue_{numeric_value_weight:.2f}"
        methods[name] = l2_normalize(
            (1.0 - value_weights) * key_matrix + value_weights * value_matrix
        )

    metric_rows: list[dict] = []
    case_frames: list[pd.DataFrame] = []
    for method, pair_matrix in methods.items():
        similarities = build_stream_similarity_matrix(
            pair_matrix,
            pairs,
            len(data),
        )
        metrics, cases = evaluate_similarity_recommendations(
            similarities,
            data,
            method,
        )
        metric_rows.append(metrics)
        case_frames.append(cases)

    return (
        pd.DataFrame(metric_rows).sort_values(
            ["macro_f1", "top1_accuracy"],
            ascending=False,
        ),
        pd.concat(case_frames, ignore_index=True),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("flat", "pair", "all"),
        default="all",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    data = load_dataset()
    print("Dataset validation passed")
    print(dataset_summary(data).to_string(index=False))
    print(f"\nLoading embedding model: {args.model}")
    model = load_model(args.model)

    if args.mode in {"flat", "all"}:
        flat_metrics, flat_cases = run_flat_experiment(data, model)
        print("\nFlat representation results")
        print(flat_metrics.to_string(index=False))
        best = flat_metrics.iloc[0]["method"]
        failures = flat_cases[
            (flat_cases["method"] == best) & ~flat_cases["correct"]
        ]
        print(f"\nBest flat method failures ({best})")
        print(
            failures[
                ["topic", "true_class", "predicted_class", "true_rank"]
            ].to_string(index=False)
            if not failures.empty
            else "None"
        )

    if args.mode in {"pair", "all"}:
        pair_metrics, pair_cases = run_pair_experiment(data, model)
        print("\nPair representation results")
        print(pair_metrics.to_string(index=False))
        best = pair_metrics.iloc[0]["method"]
        failures = pair_cases[
            (pair_cases["method"] == best) & ~pair_cases["correct"]
        ]
        print(f"\nBest pair method failures ({best})")
        print(
            failures[
                ["topic", "true_class", "predicted_class", "true_rank"]
            ].to_string(index=False)
            if not failures.empty
            else "None"
        )


if __name__ == "__main__":
    main()
