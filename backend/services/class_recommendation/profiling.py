"""Deterministic structural profiling for SmartMQTT class recommendations.

The profiler uses conservative, interpretable heuristics to describe MQTT
tags and fields and produce reproducible structural metadata.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Number
from typing import Any, Literal

ProfileSource = Literal["tag", "field"]
ValueType = Literal["numeric", "boolean", "string", "null", "array", "object"]

_WHITESPACE = re.compile(r"\s+")
_IDENTIFIER_KEYS = {"id", "uuid", "guid"}
_UNIT_KEYS = {"unit", "units"}
_TIMESTAMP_KEYS = {
    "timestamp",
    "time",
    "datetime",
    "date time",
    "created at",
    "updated at",
}


def _canonicalize(value: Any, seen: set[int] | None = None) -> Any:
    """Convert nested values into a stable JSON-compatible structure."""
    seen = seen or set()

    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    value_id = id(value)
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        if value_id in seen:
            return "<recursive>"
        seen.add(value_id)
        try:
            if isinstance(value, Mapping):
                items = [
                    (normalize_text(key, lowercase=True), _canonicalize(item, seen))
                    for key, item in value.items()
                ]
                items.sort(
                    key=lambda pair: (
                        pair[0],
                        json.dumps(pair[1], sort_keys=True, default=str),
                    )
                )
                return {key: item for key, item in items}

            items = [_canonicalize(item, seen) for item in value]
            if isinstance(value, (set, frozenset)):
                items.sort(
                    key=lambda item: json.dumps(item, sort_keys=True, default=str)
                )
            return items
        finally:
            seen.remove(value_id)

    return str(value)


def _safe_text(value: Any) -> str:
    """Create readable, deterministic text for scalar and nested values."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        canonical = _canonicalize(value)
        return json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(", ", ": "),
            default=str,
        )
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - arbitrary values may define a broken __str__
        return f"<{type(value).__name__}>"


def normalize_text(value: Any, *, lowercase: bool = False) -> str:
    """Normalize text safely without adding semantic or ontology knowledge.

    Values are converted to deterministic text, trimmed, have underscores and
    hyphens replaced by spaces, and repeated whitespace collapsed. Callers opt
    into lowercasing; profile keys use it while values retain readable case.
    """
    text = _safe_text(value).strip().replace("_", " ").replace("-", " ")
    text = _WHITESPACE.sub(" ", text)
    return text.lower() if lowercase else text


def _value_type(value: Any) -> ValueType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Number):
        return "numeric"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple, set, frozenset)):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "string"


@dataclass(frozen=True, slots=True)
class FieldProfile:
    """Structural profile for one tag or field key/value pair."""

    key: str
    value: Any
    source: ProfileSource
    value_type: ValueType
    normalized_key: str
    normalized_value: str
    is_identifier_like: bool
    is_unit_like: bool
    is_timestamp_like: bool


@dataclass(frozen=True, slots=True)
class StreamProfile:
    """Deterministically ordered profile of one MQTT stream schema."""

    topic: str
    entries: tuple[FieldProfile, ...]

    @property
    def tags(self) -> tuple[FieldProfile, ...]:
        return tuple(entry for entry in self.entries if entry.source == "tag")

    @property
    def fields(self) -> tuple[FieldProfile, ...]:
        return tuple(entry for entry in self.entries if entry.source == "field")


class StreamProfiler:
    """Build dependency-free structural profiles for MQTT stream messages."""

    def profile(
        self,
        topic: str,
        tags: Mapping[Any, Any],
        fields: Mapping[Any, Any],
    ) -> StreamProfile:
        """Profile tags then fields, sorting each source by normalized key.

        The source order is always tags before fields. Within a source, entries
        are sorted by normalized key, normalized original key, then normalized
        value so output never relies on mapping insertion order.
        """
        tag_profiles = self._profile_mapping(tags, "tag")
        field_profiles = self._profile_mapping(fields, "field")
        return StreamProfile(topic=str(topic), entries=tag_profiles + field_profiles)

    def _profile_mapping(
        self,
        values: Mapping[Any, Any],
        source: ProfileSource,
    ) -> tuple[FieldProfile, ...]:
        profiles = [
            self._profile_value(key, value, source) for key, value in values.items()
        ]
        profiles.sort(
            key=lambda item: (
                item.normalized_key,
                normalize_text(item.key, lowercase=True),
                item.normalized_value,
            )
        )
        return tuple(profiles)

    @staticmethod
    def _profile_value(
        key: Any,
        value: Any,
        source: ProfileSource,
    ) -> FieldProfile:
        key_text = _safe_text(key)
        normalized_key = normalize_text(key_text, lowercase=True)
        value_type = _value_type(value)
        key_tokens = normalized_key.split()

        return FieldProfile(
            key=key_text,
            value=value,
            source=source,
            value_type=value_type,
            normalized_key=normalized_key,
            normalized_value=normalize_text(value),
            is_identifier_like=(
                normalized_key in _IDENTIFIER_KEYS
                or bool(key_tokens and key_tokens[-1] == "id")
            ),
            is_unit_like=normalized_key in _UNIT_KEYS,
            is_timestamp_like=normalized_key in _TIMESTAMP_KEYS,
        )
