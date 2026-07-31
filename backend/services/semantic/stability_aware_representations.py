"""Stability-aware textual representations from bounded temporal state."""

from __future__ import annotations

from .representations import StreamRepresentations
from .stream_profiler import normalize_text
from .temporal_profile import TemporalEntryState, TemporalStreamProfile


class StabilityAwareRepresentationBuilder:
    """Render temporal profiles using trusted semantic evidence.

    ``missing_observations_before_exclusion`` should normally match
    ``SemanticRefreshPolicy.missing_observations_before_refresh``. Runtime
    coordination of those independently injected settings is intentionally
    outside this dependency-free builder.
    """

    def __init__(self, missing_observations_before_exclusion: int = 3):
        if (
            isinstance(missing_observations_before_exclusion, bool)
            or not isinstance(missing_observations_before_exclusion, int)
            or missing_observations_before_exclusion < 1
        ):
            raise ValueError("missing_observations_before_exclusion must be at least 1")
        self.missing_observations_before_exclusion = (
            missing_observations_before_exclusion
        )

    def build(self, profile: TemporalStreamProfile) -> StreamRepresentations:
        """Build all six representations without mutating temporal state."""
        entries = tuple(
            entry
            for entry in profile.entries
            if entry.missing_streak < self.missing_observations_before_exclusion
        )
        trusted_values = tuple(self._trusted_semantic_value(entry) for entry in entries)

        value_only = " | ".join(value for value in trusted_values if value is not None)
        key_only = " | ".join(entry.normalized_key for entry in entries)
        key_value = " | ".join(
            entry.normalized_key
            if value is None
            else f"{entry.normalized_key}: {value}"
            for entry, value in zip(entries, trusted_values, strict=True)
        )
        schema = " | ".join(
            f"{entry.normalized_key}: {entry.current_value_type}" for entry in entries
        )
        numeric_key_only = " | ".join(
            entry.normalized_key
            if entry.current_value_type == "numeric" or value is None
            else f"{entry.normalized_key}: {value}"
            for entry, value in zip(entries, trusted_values, strict=True)
        )
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

    @staticmethod
    def _trusted_semantic_value(entry: TemporalEntryState) -> str | None:
        if entry.source == "field" and entry.current_value_type == "numeric":
            return None
        if entry.is_identifier_like or entry.is_timestamp_like:
            return None
        return entry.stable_value
