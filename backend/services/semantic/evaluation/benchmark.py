"""Deterministic benchmark data for controlled semantic stream evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from .calibration import SemanticCalibrationSplit


class SemanticBenchmarkScenarioType(str, Enum):
    """Controlled forms of semantic stream evolution."""

    BENIGN_NUMERIC_DRIFT = "BENIGN_NUMERIC_DRIFT"
    IDENTIFIER_CHANGE = "IDENTIFIER_CHANGE"
    STABLE_METADATA_CHANGE = "STABLE_METADATA_CHANGE"
    KEY_ADDITION = "KEY_ADDITION"
    KEY_REMOVAL = "KEY_REMOVAL"
    TYPE_CHANGE = "TYPE_CHANGE"
    NEW_UNSEEN_CLASS = "NEW_UNSEEN_CLASS"


class SemanticBenchmarkChangeType(str, Enum):
    """Explicit ground-truth meaning of a benchmark scenario."""

    BENIGN_EVOLUTION = "BENIGN_EVOLUTION"
    MEANINGFUL_SEMANTIC_CONTEXT_CHANGE = "MEANINGFUL_SEMANTIC_CONTEXT_CHANGE"
    UNSEEN_SEMANTIC_CLASS = "UNSEEN_SEMANTIC_CLASS"


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _frozen_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class SemanticBenchmarkObservation:
    """One labeled, structured stream observation without derived semantics."""

    observation_index: int
    topic: str
    tags: Mapping[str, Any]
    fields: Mapping[str, Any]
    expected_class_name: str
    is_unseen_class: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.observation_index, bool)
            or not isinstance(self.observation_index, int)
            or self.observation_index < 0
        ):
            raise ValueError("observation_index must be a non-negative integer")
        _non_empty_string(self.topic, "topic")
        _non_empty_string(self.expected_class_name, "expected_class_name")
        if not isinstance(self.is_unseen_class, bool):
            raise TypeError("is_unseen_class must be a boolean")
        object.__setattr__(self, "tags", _frozen_mapping(self.tags, "tags"))
        object.__setattr__(self, "fields", _frozen_mapping(self.fields, "fields"))


@dataclass(frozen=True, slots=True)
class SemanticBenchmarkStream:
    """Ordered observations for one benchmark topic and class label."""

    topic: str
    expected_class_name: str
    observations: tuple[SemanticBenchmarkObservation, ...]
    split: SemanticCalibrationSplit = SemanticCalibrationSplit.REFERENCE

    def __post_init__(self) -> None:
        _non_empty_string(self.topic, "topic")
        _non_empty_string(self.expected_class_name, "expected_class_name")
        if not isinstance(self.split, SemanticCalibrationSplit):
            raise TypeError("split must be a SemanticCalibrationSplit")
        observations = tuple(self.observations)
        if not observations:
            raise ValueError("observations must not be empty")
        indices = tuple(item.observation_index for item in observations)
        if len(set(indices)) != len(indices):
            raise ValueError("observation indices must be unique within a stream")
        if indices != tuple(sorted(indices)):
            raise ValueError("observation indices must be ordered")
        if any(item.topic != self.topic for item in observations):
            raise ValueError("observation topic must match stream topic")
        if any(
            item.expected_class_name != self.expected_class_name
            for item in observations
        ):
            raise ValueError("observation class must match stream class")
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True, slots=True)
class SemanticBenchmarkScenario:
    """A named controlled evolution case and its labeled stream inputs."""

    scenario_id: str
    scenario_type: SemanticBenchmarkScenarioType
    expected_change: SemanticBenchmarkChangeType
    streams: tuple[SemanticBenchmarkStream, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.scenario_id, "scenario_id")
        if not isinstance(self.scenario_type, SemanticBenchmarkScenarioType):
            raise TypeError("scenario_type must be a SemanticBenchmarkScenarioType")
        if not isinstance(self.expected_change, SemanticBenchmarkChangeType):
            raise TypeError("expected_change must be a SemanticBenchmarkChangeType")
        streams = tuple(self.streams)
        if not streams:
            raise ValueError("streams must not be empty")
        topics = tuple(stream.topic for stream in streams)
        if len(set(topics)) != len(topics):
            raise ValueError("duplicate stream identity inside one scenario")
        object.__setattr__(self, "streams", streams)


@dataclass(frozen=True, slots=True)
class SemanticBenchmarkDataset:
    """A complete benchmark with an explicit known-versus-unseen split."""

    known_class_names: tuple[str, ...]
    unseen_class_names: tuple[str, ...]
    scenarios: tuple[SemanticBenchmarkScenario, ...]

    def __post_init__(self) -> None:
        known = tuple(self.known_class_names)
        unseen = tuple(self.unseen_class_names)
        scenarios = tuple(self.scenarios)
        if not known or not unseen:
            raise ValueError("known and unseen class names must not be empty")
        if any(
            not isinstance(name, str) or not name.strip() for name in known + unseen
        ):
            raise ValueError("class names must be non-empty strings")
        if len(set(known)) != len(known) or len(set(unseen)) != len(unseen):
            raise ValueError("class names must be unique")
        if set(known) & set(unseen):
            raise ValueError("known and unseen class names must not overlap")
        if not scenarios:
            raise ValueError("scenarios must not be empty")
        scenario_ids = tuple(item.scenario_id for item in scenarios)
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("scenario IDs must be unique")
        for observation in (
            observation
            for scenario in scenarios
            for stream in scenario.streams
            for observation in stream.observations
        ):
            if observation.is_unseen_class:
                if observation.expected_class_name not in unseen:
                    raise ValueError(
                        "unseen observation must belong to an unseen class"
                    )
            elif observation.expected_class_name not in known:
                raise ValueError("known observation must belong to a known class")
        streams = tuple(stream for scenario in scenarios for stream in scenario.streams)
        topics = tuple(stream.topic for stream in streams)
        if len(set(topics)) != len(topics):
            raise ValueError("stream topic must not cross split boundaries")
        for class_name in known:
            class_splits = {
                stream.split
                for stream in streams
                if stream.expected_class_name == class_name
            }
            if class_splits != set(SemanticCalibrationSplit):
                raise ValueError(
                    "known classes require REFERENCE, CALIBRATION, and TEST streams"
                )
        for class_name in unseen:
            class_splits = {
                stream.split
                for stream in streams
                if stream.expected_class_name == class_name
            }
            if SemanticCalibrationSplit.REFERENCE in class_splits:
                raise ValueError("unseen classes must not have REFERENCE streams")
            if class_splits != {
                SemanticCalibrationSplit.CALIBRATION,
                SemanticCalibrationSplit.TEST,
            }:
                raise ValueError("unseen classes require CALIBRATION and TEST streams")
        object.__setattr__(self, "known_class_names", known)
        object.__setattr__(self, "unseen_class_names", unseen)
        object.__setattr__(self, "scenarios", scenarios)

    @property
    def reference_streams(self) -> tuple[SemanticBenchmarkStream, ...]:
        return self._streams_for(SemanticCalibrationSplit.REFERENCE)

    @property
    def calibration_streams(self) -> tuple[SemanticBenchmarkStream, ...]:
        return self._streams_for(SemanticCalibrationSplit.CALIBRATION)

    @property
    def test_streams(self) -> tuple[SemanticBenchmarkStream, ...]:
        return self._streams_for(SemanticCalibrationSplit.TEST)

    def _streams_for(
        self, split: SemanticCalibrationSplit
    ) -> tuple[SemanticBenchmarkStream, ...]:
        return tuple(
            stream
            for scenario in self.scenarios
            for stream in scenario.streams
            if stream.split is split
        )


class SemanticBenchmarkBuilder:
    """Build a fixed benchmark without production semantic service calls."""

    def build(self) -> SemanticBenchmarkDataset:
        """Return the same labeled scenarios on every invocation."""
        return SemanticBenchmarkDataset(
            known_class_names=(
                "Temperature Sensor",
                "Humidity Sensor",
                "Air Quality",
                "Traffic Count",
                "Energy Consumption",
                "Occupancy",
            ),
            unseen_class_names=("Vibration Sensor",),
            scenarios=self._assign_splits(
                (
                    self._benign_numeric_drift(),
                    self._identifier_change(),
                    self._stable_metadata_change(),
                    self._key_addition(),
                    self._key_removal(),
                    self._type_change(),
                    self._new_unseen_class(),
                )
            ),
        )

    @staticmethod
    def _assign_splits(
        scenarios: tuple[SemanticBenchmarkScenario, ...],
    ) -> tuple[SemanticBenchmarkScenario, ...]:
        assigned = []
        for scenario in scenarios:
            streams = []
            for stream in scenario.streams:
                splits = (
                    (
                        SemanticCalibrationSplit.CALIBRATION,
                        SemanticCalibrationSplit.TEST,
                    )
                    if stream.expected_class_name == "Vibration Sensor"
                    else tuple(SemanticCalibrationSplit)
                )
                for split in splits:
                    suffix = split.value.lower()
                    observations = tuple(
                        SemanticBenchmarkObservation(
                            item.observation_index,
                            f"{item.topic}/{suffix}",
                            item.tags,
                            item.fields,
                            item.expected_class_name,
                            item.is_unseen_class,
                        )
                        for item in stream.observations
                    )
                    streams.append(
                        SemanticBenchmarkStream(
                            f"{stream.topic}/{suffix}",
                            stream.expected_class_name,
                            observations,
                            split,
                        )
                    )
            assigned.append(
                SemanticBenchmarkScenario(
                    scenario.scenario_id,
                    scenario.scenario_type,
                    scenario.expected_change,
                    tuple(streams),
                )
            )
        return tuple(assigned)

    @staticmethod
    def _observation(
        index: int,
        topic: str,
        tags: Mapping[str, Any],
        fields: Mapping[str, Any],
        class_name: str,
        unseen: bool = False,
    ) -> SemanticBenchmarkObservation:
        return SemanticBenchmarkObservation(
            observation_index=index,
            topic=topic,
            tags=tags,
            fields=fields,
            expected_class_name=class_name,
            is_unseen_class=unseen,
        )

    def _benign_numeric_drift(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/temperature/lab-01"
        return SemanticBenchmarkScenario(
            "benign-numeric-drift",
            SemanticBenchmarkScenarioType.BENIGN_NUMERIC_DRIFT,
            SemanticBenchmarkChangeType.BENIGN_EVOLUTION,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Temperature Sensor",
                    tuple(
                        self._observation(
                            index,
                            topic,
                            {"location": "lab", "sensor_id": "t01"},
                            {"temperature": value, "unit": "C"},
                            "Temperature Sensor",
                        )
                        for index, value in enumerate((21.0, 21.8, 22.4))
                    ),
                ),
            ),
        )

    def _identifier_change(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/humidity/greenhouse-01"
        return SemanticBenchmarkScenario(
            "identifier-change",
            SemanticBenchmarkScenarioType.IDENTIFIER_CHANGE,
            SemanticBenchmarkChangeType.BENIGN_EVOLUTION,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Humidity Sensor",
                    (
                        self._observation(
                            0,
                            topic,
                            {"sensor_id": "a01"},
                            {"humidity": 45.0},
                            "Humidity Sensor",
                        ),
                        self._observation(
                            1,
                            topic,
                            {"sensor_id": "b77"},
                            {"humidity": 45.2},
                            "Humidity Sensor",
                        ),
                    ),
                ),
            ),
        )

    def _stable_metadata_change(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/air-quality/room-01"
        return SemanticBenchmarkScenario(
            "stable-metadata-change",
            SemanticBenchmarkScenarioType.STABLE_METADATA_CHANGE,
            SemanticBenchmarkChangeType.MEANINGFUL_SEMANTIC_CONTEXT_CHANGE,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Air Quality",
                    tuple(
                        self._observation(
                            index,
                            topic,
                            {"location": location},
                            {"co2": 620},
                            "Air Quality",
                        )
                        for index, location in enumerate(
                            ("room_a", "room_a", "room_b", "room_b")
                        )
                    ),
                ),
            ),
        )

    def _key_addition(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/traffic/intersection-01"
        return SemanticBenchmarkScenario(
            "key-addition",
            SemanticBenchmarkScenarioType.KEY_ADDITION,
            SemanticBenchmarkChangeType.MEANINGFUL_SEMANTIC_CONTEXT_CHANGE,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Traffic Count",
                    (
                        self._observation(
                            0,
                            topic,
                            {"intersection": "north"},
                            {"count": 12},
                            "Traffic Count",
                        ),
                        self._observation(
                            1,
                            topic,
                            {"intersection": "north"},
                            {"count": 14, "lane": "eastbound"},
                            "Traffic Count",
                        ),
                    ),
                ),
            ),
        )

    def _key_removal(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/energy/building-01"
        return SemanticBenchmarkScenario(
            "key-removal",
            SemanticBenchmarkScenarioType.KEY_REMOVAL,
            SemanticBenchmarkChangeType.MEANINGFUL_SEMANTIC_CONTEXT_CHANGE,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Energy Consumption",
                    (
                        self._observation(
                            0,
                            topic,
                            {"building": "a"},
                            {"kwh": 7.4, "voltage": 230.0},
                            "Energy Consumption",
                        ),
                        self._observation(
                            1,
                            topic,
                            {"building": "a"},
                            {"kwh": 7.6},
                            "Energy Consumption",
                        ),
                        self._observation(
                            2,
                            topic,
                            {"building": "a"},
                            {"kwh": 7.8},
                            "Energy Consumption",
                        ),
                    ),
                ),
            ),
        )

    def _type_change(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/occupancy/floor-01"
        return SemanticBenchmarkScenario(
            "type-change",
            SemanticBenchmarkScenarioType.TYPE_CHANGE,
            SemanticBenchmarkChangeType.MEANINGFUL_SEMANTIC_CONTEXT_CHANGE,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Occupancy",
                    (
                        self._observation(
                            0, topic, {"floor": "one"}, {"occupied": 1}, "Occupancy"
                        ),
                        self._observation(
                            1, topic, {"floor": "one"}, {"occupied": "yes"}, "Occupancy"
                        ),
                    ),
                ),
            ),
        )

    def _new_unseen_class(self) -> SemanticBenchmarkScenario:
        topic = "benchmark/vibration/motor-01"
        return SemanticBenchmarkScenario(
            "new-unseen-class",
            SemanticBenchmarkScenarioType.NEW_UNSEEN_CLASS,
            SemanticBenchmarkChangeType.UNSEEN_SEMANTIC_CLASS,
            (
                SemanticBenchmarkStream(
                    topic,
                    "Vibration Sensor",
                    (
                        self._observation(
                            0,
                            topic,
                            {"machine": "motor-01"},
                            {"vibration": 0.12},
                            "Vibration Sensor",
                            unseen=True,
                        ),
                        self._observation(
                            1,
                            topic,
                            {"machine": "motor-01"},
                            {"vibration": 0.18},
                            "Vibration Sensor",
                            unseen=True,
                        ),
                    ),
                ),
            ),
        )
