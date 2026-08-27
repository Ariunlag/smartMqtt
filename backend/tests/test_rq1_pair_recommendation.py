from services.class_recommendation.evaluation.rq1_benchmark import (
    CONDITIONS,
    RQ1BenchmarkRunner,
)
from services.class_recommendation.evaluation.rq1_dataset import (
    DuplicateFilterStats,
    RQ1Dataset,
    RQ1Example,
    RQ1SourceKind,
    RQ1Split,
)


class FeatureModel:
    def encode(self, texts):
        return [
            [1.0, 0.0]
            if "temperature" in text or "temp" in text
            else [0.0, 1.0]
            if "humidity" in text or "humid" in text
            else [0.5, 0.5]
            for text in texts
        ]


def _example(stream_id, topic, key, label, split):
    return RQ1Example(
        stream_id=stream_id,
        topic=topic,
        tags={},
        fields={key: 1.0},
        label=label,
        split=split,
        source_id=f"source-{stream_id}",
        source_kind=RQ1SourceKind.CONTROLLED,
    )


def test_rq1_uses_registry_pair_evidence_stream_context_and_no_open_world_states():
    examples = (
        _example(
            "tc1",
            "lab/temperature/1",
            "temperature",
            "Temperature",
            RQ1Split.CALIBRATION,
        ),
        _example("tc2", "lab/temp/2", "temp", "Temperature", RQ1Split.CALIBRATION),
        _example("hc1", "lab/humidity/1", "humidity", "Humidity", RQ1Split.CALIBRATION),
        _example("hc2", "lab/humid/2", "humid", "Humidity", RQ1Split.CALIBRATION),
        _example(
            "tv", "lab/temperature/v", "temperature", "Temperature", RQ1Split.VALIDATION
        ),
        _example("hv", "lab/humidity/v", "humidity", "Humidity", RQ1Split.VALIDATION),
    )
    dataset = RQ1Dataset(
        "pair-rq1",
        "1",
        42,
        examples,
        "fixture",
        DuplicateFilterStats(len(examples), len(examples), 0, 0),
    )

    result = RQ1BenchmarkRunner(
        FeatureModel(), model_name="feature-fixture", device="cpu"
    ).run(dataset)

    assert tuple(row["condition"] for row in result.summary_rows) == CONDITIONS
    assert CONDITIONS == (
        "key",
        "value",
        "key_value",
        "schema",
        "stream_context",
        "equal_mean",
    )
    assert result.metadata["architecture"] == (
        "pair-level-four-evidence-plus-shared-stream-context"
    )
    assert result.metadata["embedding_calls"] == len(examples) * 2
    assert (
        next(row for row in result.summary_rows if row["condition"] == "key")[
            "top1_accuracy"
        ]
        == 1.0
    )
    assert all("automated_state" not in row for row in result.predictions)
