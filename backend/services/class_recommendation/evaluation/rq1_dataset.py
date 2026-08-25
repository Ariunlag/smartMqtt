"""Versioned RQ1 dataset contract and canonical duplicate leakage controls."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


class RQ1Split(str, Enum):
    """Dataset partitions with a fixed calibration-to-test order."""

    CALIBRATION = "CALIBRATION"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class RQ1SourceKind(str, Enum):
    """Sources that must remain separate in reported metrics."""

    CONTROLLED = "CONTROLLED"
    REAL = "REAL"


class DuplicateDisposition(str, Enum):
    """Phase 2 duplicate identity outcomes represented in a dataset."""

    CANONICAL = "CANONICAL"
    CONFIRMED_ALIAS = "CONFIRMED_ALIAS"
    KEEP_BOTH = "KEEP_BOTH"


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    if any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError(f"{name} keys must be non-empty strings")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class RQ1Example:
    """One labeled stream example before any representation is derived."""

    stream_id: str
    topic: str
    tags: Mapping[str, Any]
    fields: Mapping[str, Any]
    label: str
    split: RQ1Split
    source_id: str
    source_kind: RQ1SourceKind
    duplicate_disposition: DuplicateDisposition = DuplicateDisposition.CANONICAL
    canonical_stream_id: str | None = None
    decision_source: str = "AUTOMATED"
    authoritative_label: str | None = None

    def __post_init__(self) -> None:
        for name in ("stream_id", "topic", "label", "source_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        if not isinstance(self.split, RQ1Split):
            raise TypeError("split must be an RQ1Split")
        if not isinstance(self.source_kind, RQ1SourceKind):
            raise TypeError("source_kind must be an RQ1SourceKind")
        if not isinstance(self.duplicate_disposition, DuplicateDisposition):
            raise TypeError("duplicate_disposition must be a DuplicateDisposition")
        object.__setattr__(self, "tags", _mapping(self.tags, "tags"))
        object.__setattr__(self, "fields", _mapping(self.fields, "fields"))
        if not self.tags and not self.fields:
            raise ValueError("an example requires at least one tag or field")
        if self.duplicate_disposition is DuplicateDisposition.CONFIRMED_ALIAS:
            _required_text(self.canonical_stream_id, "canonical_stream_id")
            if self.canonical_stream_id == self.stream_id:
                raise ValueError(
                    "a confirmed alias cannot identify itself as canonical"
                )
        elif self.canonical_stream_id is not None:
            _required_text(self.canonical_stream_id, "canonical_stream_id")
        if self.decision_source not in {"AUTOMATED", "HUMAN_CONFIRMED"}:
            raise ValueError("decision_source must be AUTOMATED or HUMAN_CONFIRMED")
        if self.authoritative_label is not None:
            _required_text(self.authoritative_label, "authoritative_label")


@dataclass(frozen=True, slots=True)
class DuplicateFilterStats:
    input_count: int
    retained_count: int
    confirmed_aliases_excluded: int
    keep_both_retained: int


@dataclass(frozen=True, slots=True)
class RQ1Dataset:
    """Validated benchmark data with final-test isolation."""

    dataset_id: str
    version: str
    seed: int
    examples: tuple[RQ1Example, ...]
    sha256: str
    duplicate_stats: DuplicateFilterStats

    def for_split(self, split: RQ1Split) -> tuple[RQ1Example, ...]:
        return tuple(item for item in self.examples if item.split is split)

    @property
    def calibration(self) -> tuple[RQ1Example, ...]:
        return self.for_split(RQ1Split.CALIBRATION)

    @property
    def validation(self) -> tuple[RQ1Example, ...]:
        return self.for_split(RQ1Split.VALIDATION)

    @property
    def test(self) -> tuple[RQ1Example, ...]:
        return self.for_split(RQ1Split.TEST)


def load_rq1_dataset(path: str | Path) -> RQ1Dataset:
    """Load, validate, canonical-filter, and hash a dataset JSON document."""
    source_path = Path(path)
    raw_bytes = source_path.read_bytes()
    try:
        document = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid benchmark JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise TypeError("benchmark root must be an object")
    if document.get("schema_version") != "smartmqtt-rq1/v1":
        raise ValueError("schema_version must be 'smartmqtt-rq1/v1'")
    dataset_id = _required_text(document.get("dataset_id"), "dataset_id")
    version = _required_text(document.get("version"), "version")
    seed = document.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    records = document.get("examples")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise TypeError("examples must be an array")
    examples = tuple(
        _parse_example(record, index) for index, record in enumerate(records)
    )
    if not examples:
        raise ValueError("examples must not be empty")
    ids = [item.stream_id for item in examples]
    if len(ids) != len(set(ids)):
        raise ValueError("stream_id values must be unique")
    by_id = {item.stream_id: item for item in examples}
    for alias in (
        item
        for item in examples
        if item.duplicate_disposition is DuplicateDisposition.CONFIRMED_ALIAS
    ):
        canonical = by_id.get(alias.canonical_stream_id)
        if canonical is None:
            raise ValueError(
                f"confirmed alias '{alias.stream_id}' references a missing canonical"
            )
        if canonical.duplicate_disposition is not DuplicateDisposition.CANONICAL:
            raise ValueError("confirmed aliases must reference a canonical record")
        if canonical.split is not alias.split:
            raise ValueError("confirmed alias and canonical must use the same split")
        if canonical.label != alias.label:
            raise ValueError("confirmed alias and canonical labels must match")

    retained = tuple(
        item
        for item in examples
        if item.duplicate_disposition is not DuplicateDisposition.CONFIRMED_ALIAS
    )
    stats = DuplicateFilterStats(
        input_count=len(examples),
        retained_count=len(retained),
        confirmed_aliases_excluded=len(examples) - len(retained),
        keep_both_retained=sum(
            item.duplicate_disposition is DuplicateDisposition.KEEP_BOTH
            for item in retained
        ),
    )
    _validate_splits(retained)
    return RQ1Dataset(
        dataset_id=dataset_id,
        version=version,
        seed=seed,
        examples=retained,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        duplicate_stats=stats,
    )


def _parse_example(record: object, index: int) -> RQ1Example:
    if not isinstance(record, Mapping):
        raise TypeError(f"examples[{index}] must be an object")
    try:
        return RQ1Example(
            stream_id=record.get("stream_id"),
            topic=record.get("topic"),
            tags=record.get("tags", {}),
            fields=record.get("fields", record.get("schema", {})),
            label=record.get("label"),
            split=RQ1Split(record.get("split")),
            source_id=record.get("source_id"),
            source_kind=RQ1SourceKind(record.get("source_kind")),
            duplicate_disposition=DuplicateDisposition(
                record.get("duplicate_disposition", "CANONICAL")
            ),
            canonical_stream_id=record.get("canonical_stream_id"),
            decision_source=record.get("decision_source", "AUTOMATED"),
            authoritative_label=record.get("authoritative_label"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid examples[{index}]: {exc}") from exc


def _validate_splits(examples: tuple[RQ1Example, ...]) -> None:
    counts = Counter(item.split for item in examples)
    missing = [split.value for split in RQ1Split if not counts[split]]
    if missing:
        raise ValueError(f"dataset is missing required splits: {', '.join(missing)}")
    identities: dict[str, RQ1Split] = {}
    source_records: dict[str, RQ1Split] = {}
    topics: dict[str, RQ1Split] = {}
    for item in examples:
        if item.source_id in source_records:
            raise ValueError(f"source record '{item.source_id}' is duplicated")
        logical_id = item.canonical_stream_id or item.stream_id
        for name, key, index in (
            ("logical stream", logical_id, identities),
            ("source record", item.source_id, source_records),
            ("topic", item.topic, topics),
        ):
            previous = index.setdefault(key, item.split)
            if previous is not item.split:
                raise ValueError(
                    f"split leakage: {name} '{key}' appears in "
                    f"{previous.value} and {item.split.value}"
                )
