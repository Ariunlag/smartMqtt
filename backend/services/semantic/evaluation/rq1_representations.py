"""Deterministic production and experimental representations for RQ1."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ..representations import RepresentationBuilder
from ..stream_profiler import StreamProfiler
from .rq1_dataset import RQ1Example


class RQ1Variant(str, Enum):
    """Production views and explicitly named experimental conditions."""

    VALUE_ONLY = "VALUE_ONLY"
    KEY_ONLY = "KEY_ONLY"
    KEY_VALUE = "KEY_VALUE"
    SCHEMA = "SCHEMA"
    NUMERIC_KEY_ONLY = "NUMERIC_KEY_ONLY"
    TOPIC_KEY_VALUE = "TOPIC_KEY_VALUE"
    APPROACH1_KEY_VALUE_UNITS = "APPROACH1_KEY_VALUE_UNITS"
    APPROACH2_INDEPENDENT = "APPROACH2_INDEPENDENT"
    APPROACH3_TYPED_RELATION = "APPROACH3_TYPED_RELATION"
    NUMERIC_RAW = "NUMERIC_RAW"
    NUMERIC_TYPE = "NUMERIC_TYPE"
    NUMERIC_BUCKET = "NUMERIC_BUCKET"


PRODUCTION_VARIANTS = (
    RQ1Variant.VALUE_ONLY,
    RQ1Variant.KEY_ONLY,
    RQ1Variant.KEY_VALUE,
    RQ1Variant.SCHEMA,
    RQ1Variant.NUMERIC_KEY_ONLY,
    RQ1Variant.TOPIC_KEY_VALUE,
)


class IndependentFusion(str, Enum):
    MEAN = "MEAN"
    WEIGHTED_MEAN = "WEIGHTED_MEAN"
    CONCATENATE = "CONCATENATE"


@dataclass(frozen=True, slots=True)
class RQ1RepresentationConfig:
    independent_fusion: IndependentFusion = IndependentFusion.MEAN
    key_weight: float = 0.5
    numeric_bucket_boundaries: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.independent_fusion, IndependentFusion):
            raise TypeError("independent_fusion must be an IndependentFusion")
        if not math.isfinite(self.key_weight) or not 0.0 <= self.key_weight <= 1.0:
            raise ValueError("key_weight must be within [0, 1]")
        boundaries = tuple(float(item) for item in self.numeric_bucket_boundaries)
        if any(not math.isfinite(item) for item in boundaries):
            raise ValueError("numeric bucket boundaries must be finite")
        if boundaries != tuple(sorted(set(boundaries))):
            raise ValueError("numeric bucket boundaries must be unique and ascending")
        object.__setattr__(self, "numeric_bucket_boundaries", boundaries)


@dataclass(frozen=True, slots=True)
class RQ1Representation:
    """One or more texts plus the rule for producing one comparable vector."""

    texts: tuple[str, ...]
    fusion: IndependentFusion = IndependentFusion.MEAN
    key_weight: float = 0.5


class RQ1RepresentationBuilder:
    """Build experimental texts without changing the production builder."""

    def __init__(self) -> None:
        self._profiler = StreamProfiler()
        self._production = RepresentationBuilder(self._profiler)

    def build(
        self,
        example: RQ1Example,
        variant: RQ1Variant,
        config: RQ1RepresentationConfig | None = None,
    ) -> RQ1Representation:
        config = config or RQ1RepresentationConfig()
        if not isinstance(variant, RQ1Variant):
            raise TypeError("variant must be an RQ1Variant")
        profile = self._profiler.profile(example.topic, example.tags, example.fields)
        if variant in PRODUCTION_VARIANTS:
            exact = self._production.build_from_profile(profile).as_dict()
            return RQ1Representation((exact[variant.value.lower()] or "<empty>",))
        entries = profile.entries
        if variant is RQ1Variant.APPROACH1_KEY_VALUE_UNITS:
            text = " | ".join(
                f"{item.normalized_key}:{item.normalized_value}" for item in entries
            )
        elif variant is RQ1Variant.APPROACH2_INDEPENDENT:
            keys = " | ".join(item.normalized_key for item in entries) or "<empty>"
            values = " | ".join(item.normalized_value for item in entries) or "<empty>"
            return RQ1Representation(
                (keys, values), config.independent_fusion, config.key_weight
            )
        elif variant is RQ1Variant.APPROACH3_TYPED_RELATION:
            text = " | ".join(self._typed_relation(item) for item in entries)
        elif variant is RQ1Variant.NUMERIC_RAW:
            text = " | ".join(
                f"{item.normalized_key}: {item.normalized_value}" for item in entries
            )
        elif variant is RQ1Variant.NUMERIC_TYPE:
            text = " | ".join(
                f"{item.normalized_key}: numeric"
                if item.is_numeric
                else f"{item.normalized_key}: {item.normalized_value}"
                for item in entries
            )
        elif variant is RQ1Variant.NUMERIC_BUCKET:
            if not config.numeric_bucket_boundaries:
                raise ValueError("NUMERIC_BUCKET requires numeric_bucket_boundaries")
            text = " | ".join(
                self._bucket_text(item, config.numeric_bucket_boundaries)
                for item in entries
            )
        else:  # pragma: no cover - exhaustive enum guard
            raise AssertionError(variant)
        return RQ1Representation((text or "<empty>",))

    @staticmethod
    def _typed_relation(item) -> str:
        if item.is_numeric:
            return f"{item.normalized_key} measurement {item.normalized_value}"
        if item.source == "field":
            return f"{item.normalized_key} is {item.normalized_value}"
        return f"{item.normalized_key} {item.normalized_value}"

    @staticmethod
    def _bucket_text(item, boundaries: tuple[float, ...]) -> str:
        if not item.is_numeric:
            return f"{item.normalized_key}: {item.normalized_value}"
        value = float(item.value)
        bucket = sum(value >= boundary for boundary in boundaries)
        return f"{item.normalized_key}: numeric bucket {bucket}"


def fuse_vectors(
    vectors: tuple[tuple[float, ...], ...],
    representation: RQ1Representation,
) -> tuple[float, ...]:
    """Fuse Approach 2 vectors using its explicit experimental configuration."""
    if not vectors or any(not vector for vector in vectors):
        raise ValueError("embedding vectors must not be empty")
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise ValueError("embedding vectors must have equal dimensions")
    if len(vectors) == 1:
        return vectors[0]
    if representation.fusion is IndependentFusion.CONCATENATE:
        return tuple(value for vector in vectors for value in vector)
    weight = (
        representation.key_weight
        if representation.fusion is IndependentFusion.WEIGHTED_MEAN
        else 0.5
    )
    return tuple(
        weight * vectors[0][index] + (1.0 - weight) * vectors[1][index]
        for index in range(dimension)
    )
