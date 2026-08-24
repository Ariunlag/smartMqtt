import json
from dataclasses import asdict
from pathlib import Path

import pytest
from services.embedding.base_model import BaseEmbeddingModel
from services.semantic.evaluation.rq1_benchmark import (
    RQ1BenchmarkRunner,
    RQ1Condition,
    RQ1DecisionConfig,
    write_rq1_artifacts,
)
from services.semantic.evaluation.rq1_dataset import (
    DuplicateDisposition,
    RQ1Example,
    RQ1SourceKind,
    RQ1Split,
    load_rq1_dataset,
)
from services.semantic.evaluation.rq1_metrics import (
    RQ1Prediction,
    compute_quality_metrics,
)
from services.semantic.evaluation.rq1_representations import (
    PRODUCTION_VARIANTS,
    IndependentFusion,
    RQ1RepresentationBuilder,
    RQ1RepresentationConfig,
    RQ1Variant,
    fuse_vectors,
)
from services.semantic.representations import RepresentationBuilder

FIXTURE = Path(__file__).parent / "fixtures" / "rq1_controlled_smoke_v1.json"


class TokenEmbedding(BaseEmbeddingModel):
    def encode(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    float("temp" in lowered or "heat" in lowered),
                    float("voltage" in lowered),
                    float("pressure" in lowered),
                    0.1,
                ]
            )
        return vectors


def example(fields=None, tags=None):
    return RQ1Example(
        "stream",
        "factory/line_one",
        {"location": "Warehouse_01"} if tags is None else tags,
        {"status": "active", "temperature": 22.5} if fields is None else fields,
        "temperature",
        RQ1Split.VALIDATION,
        "source/stream",
        RQ1SourceKind.CONTROLLED,
    )


def prediction(expected, state, predicted, ranking, *, unknown=False, human=False):
    return RQ1Prediction(
        expected,
        "CONTROLLED",
        expected,
        unknown,
        state,
        predicted,
        ranking,
        "test",
        0.8,
        0.2,
        {},
        {},
        1,
        "HUMAN_CONFIRMED" if human else "AUTOMATED",
        expected if human else None,
    )


def test_existing_six_texts_are_exact_and_experimental_builds_are_deterministic():
    item = example()
    production = RepresentationBuilder().build(item.topic, item.tags, item.fields)
    builder = RQ1RepresentationBuilder()

    for variant in PRODUCTION_VARIANTS:
        first = builder.build(item, variant)
        second = builder.build(item, variant)
        assert first == second
        assert first.texts == (production.as_dict()[variant.value.lower()],)

    assert builder.build(item, RQ1Variant.APPROACH1_KEY_VALUE_UNITS).texts == (
        "location:Warehouse 01 | status:active | temperature:22.5",
    )
    assert builder.build(item, RQ1Variant.APPROACH3_TYPED_RELATION).texts == (
        "location Warehouse 01 | status is active | temperature measurement 22.5",
    )


def test_independent_fusion_and_numeric_ablation_are_explicit():
    builder = RQ1RepresentationBuilder()
    item = example(fields={"temperature": 22.5, "status": "active"}, tags={})
    independent = builder.build(
        item,
        RQ1Variant.APPROACH2_INDEPENDENT,
        RQ1RepresentationConfig(IndependentFusion.WEIGHTED_MEAN, 0.75),
    )
    assert independent.texts == ("status | temperature", "active | 22.5")
    assert fuse_vectors(((1.0, 0.0), (0.0, 1.0)), independent) == (0.75, 0.25)
    assert "22.5" in builder.build(item, RQ1Variant.NUMERIC_RAW).texts[0]
    assert (
        "temperature: numeric" in builder.build(item, RQ1Variant.NUMERIC_TYPE).texts[0]
    )
    bucket = builder.build(
        item,
        RQ1Variant.NUMERIC_BUCKET,
        RQ1RepresentationConfig(numeric_bucket_boundaries=(0.0, 20.0, 30.0)),
    )
    assert "temperature: numeric bucket 2" in bucket.texts[0]
    assert "low" not in bucket.texts[0]
    with pytest.raises(ValueError, match="boundaries"):
        builder.build(item, RQ1Variant.NUMERIC_BUCKET)


def test_dataset_filters_aliases_retains_keep_both_and_separates_sources():
    dataset = load_rq1_dataset(FIXTURE)
    ids = {item.stream_id for item in dataset.examples}
    assert "cal-temp-alias" not in ids
    assert {"val-keep-a", "val-keep-b"} <= ids
    assert dataset.duplicate_stats.confirmed_aliases_excluded == 1
    assert dataset.duplicate_stats.keep_both_retained == 2
    assert {item.source_kind for item in dataset.examples} == set(RQ1SourceKind)


def test_split_leakage_and_invalid_labels_fail_clearly(tmp_path):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["examples"][-1]["source_id"] = document["examples"][0]["source_id"]
    leaking = tmp_path / "leaking.json"
    leaking.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="source record.*duplicated"):
        load_rq1_dataset(leaking)

    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del document["examples"][0]["label"]
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="label"):
        load_rq1_dataset(invalid)

    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    alias = next(
        item
        for item in document["examples"]
        if item.get("duplicate_disposition") == "CONFIRMED_ALIAS"
    )
    alias["canonical_stream_id"] = "missing"
    broken_alias = tmp_path / "broken-alias.json"
    broken_alias.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="missing canonical"):
        load_rq1_dataset(broken_alias)


def test_hand_verifiable_metrics_and_confusion_order():
    records = (
        prediction("alpha", "KNOWN", "alpha", ("alpha", "beta")),
        prediction("beta", "KNOWN", "alpha", ("alpha", "beta")),
        prediction("novel", "UNKNOWN", None, ("beta", "alpha"), unknown=True),
        prediction("other", "KNOWN", "beta", ("beta", "alpha"), unknown=True),
    )
    metrics = compute_quality_metrics(records)
    assert metrics.accuracy == 0.5
    assert metrics.unknown_precision == 1.0
    assert metrics.unknown_recall == 0.5
    assert metrics.known_class_false_positive_rate == 0.5
    assert metrics.top1_accuracy == 0.5
    assert metrics.top3_accuracy == 1.0
    assert metrics.mean_reciprocal_rank == 0.75
    assert metrics.confusion_labels == ("alpha", "beta", "UNKNOWN")
    assert metrics.confusion_matrix == ((1, 0, 0), (1, 0, 0), (0, 1, 1))


def test_human_confirmed_is_not_automated_classifier_success():
    record = prediction(
        "new-class", "KNOWN", "wrong", ("wrong",), unknown=True, human=True
    )
    automated = compute_quality_metrics((record,))
    authoritative = compute_quality_metrics((record,), authoritative=True)
    assert automated.accuracy == 0.0
    assert authoritative.accuracy == 1.0


def test_runner_metadata_artifacts_and_source_metrics(tmp_path):
    dataset = load_rq1_dataset(FIXTURE)
    runner = RQ1BenchmarkRunner(
        TokenEmbedding(),
        model_name="test-token-model",
        device="cpu",
        decision_config=RQ1DecisionConfig(0.2, 0.0, -0.5),
    )
    result = runner.run(
        dataset,
        (
            RQ1Condition("KEY_ONLY", (RQ1Variant.KEY_ONLY,)),
            RQ1Condition(
                "EQUAL",
                (RQ1Variant.KEY_ONLY, RQ1Variant.KEY_VALUE),
                "EQUAL_VOTE",
            ),
            RQ1Condition(
                "CALIBRATED",
                (RQ1Variant.KEY_ONLY, RQ1Variant.KEY_VALUE),
                "STATIC_WEIGHTS",
            ),
        ),
        seed=42,
        bootstrap_repetitions=10,
        timestamp="2026-08-24T00:00:00+00:00",
    )
    assert result.metadata["git_commit"]
    assert result.metadata["dataset_sha256"] == dataset.sha256
    assert result.metadata["embedding_model"] == "test-token-model"
    assert result.metadata["decision_config"] == asdict(
        RQ1DecisionConfig(0.2, 0.0, -0.5)
    )
    assert {row["source_kind"] for row in result.summary_rows} == {
        "CONTROLLED",
        "REAL",
    }
    paths = write_rq1_artifacts(result, tmp_path)
    assert set(paths) == {"json", "jsonl", "csv"}
    artifact = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert artifact["metadata"]["random_seed"] == 42
    assert "authoritative_after_feedback" in artifact["summary_rows"][0]
    assert "vector" not in json.dumps(artifact["predictions"]).lower()
    calibrated = next(
        item for item in result.metadata["conditions"] if item["name"] == "CALIBRATED"
    )
    assert set(calibrated["resolved_static_weights"]) == {"KEY_ONLY", "KEY_VALUE"}


def test_final_test_content_cannot_influence_validation_evidence(tmp_path):
    first_document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second_document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for item in second_document["examples"]:
        if item["split"] == "TEST":
            item["fields"] = {"completely_different_test_only_key": "ignored"}
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_path.write_text(json.dumps(first_document), encoding="utf-8")
    second_path.write_text(json.dumps(second_document), encoding="utf-8")
    runner = RQ1BenchmarkRunner(
        TokenEmbedding(),
        model_name="test-token-model",
        device="cpu",
        decision_config=RQ1DecisionConfig(0.2, 0.0, -0.5),
    )
    condition = (
        RQ1Condition(
            "CALIBRATED",
            (RQ1Variant.KEY_ONLY, RQ1Variant.KEY_VALUE),
            "STATIC_WEIGHTS",
        ),
    )
    first = runner.run(
        load_rq1_dataset(first_path),
        condition,
        bootstrap_repetitions=5,
        timestamp="fixed",
    )
    second = runner.run(
        load_rq1_dataset(second_path),
        condition,
        bootstrap_repetitions=5,
        timestamp="fixed",
    )
    assert first.predictions == second.predictions
    assert first.centroid_correctness == second.centroid_correctness
    assert first.metadata["conditions"] == second.metadata["conditions"]


def test_experimental_variants_do_not_mutate_production_defaults():
    item = example()
    before = RepresentationBuilder().build(item.topic, item.tags, item.fields)
    RQ1RepresentationBuilder().build(
        item,
        RQ1Variant.NUMERIC_BUCKET,
        RQ1RepresentationConfig(numeric_bucket_boundaries=(0.0, 10.0)),
    )
    after = RepresentationBuilder().build(item.topic, item.tags, item.fields)
    assert after == before
    assert DuplicateDisposition.KEEP_BOTH.value == "KEEP_BOTH"
