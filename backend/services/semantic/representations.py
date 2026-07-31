"""Deterministic textual representations for SmartMQTT streams.

The builder renders stream profiles into deterministic textual representations
for comparison, analysis, and downstream processing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from .stream_profiler import StreamProfile, StreamProfiler, normalize_text


@dataclass(frozen=True, slots=True)
class StreamRepresentations:
    """Six deterministic textual views of one MQTT stream."""

    value_only: str
    key_only: str
    key_value: str
    schema: str
    numeric_key_only: str
    topic_key_value: str

    def as_dict(self) -> dict[str, str]:
        """Return a stable dictionary suitable for serialization."""
        return asdict(self)


class RepresentationBuilder:
    """Build candidate representations from dependency-free stream profiles."""

    def __init__(self, profiler: StreamProfiler | None = None):
        self.profiler = profiler or StreamProfiler()

    def build(
        self,
        topic: str,
        tags: Mapping[Any, Any],
        fields: Mapping[Any, Any],
    ) -> StreamRepresentations:
        """Profile a message and render all supported candidate representations."""
        return self.build_from_profile(self.profiler.profile(topic, tags, fields))

    @staticmethod
    def build_from_profile(profile: StreamProfile) -> StreamRepresentations:
        """Render entries in the stable order defined by ``StreamProfiler``."""
        values = [entry.normalized_value for entry in profile.entries]
        keys = [entry.normalized_key for entry in profile.entries]
        key_values = [
            f"{entry.normalized_key}: {entry.normalized_value}"
            for entry in profile.entries
        ]
        schema_items = [
            f"{entry.normalized_key}: {entry.value_type}" for entry in profile.entries
        ]
        numeric_key_items = [
            entry.normalized_key
            if entry.is_numeric
            else f"{entry.normalized_key}: {entry.normalized_value}"
            for entry in profile.entries
        ]

        value_only = " | ".join(values)
        key_only = " | ".join(keys)
        key_value = " | ".join(key_values)
        schema = " | ".join(schema_items)
        numeric_key_only = " | ".join(numeric_key_items)
        normalized_topic = normalize_text(
            profile.topic.replace("/", " "), lowercase=True
        )
        topic_key_value = " | ".join(
            part for part in (normalized_topic, key_value) if part
        )

        return StreamRepresentations(
            value_only=value_only,
            key_only=key_only,
            key_value=key_value,
            schema=schema,
            numeric_key_only=numeric_key_only,
            topic_key_value=topic_key_value,
        )
