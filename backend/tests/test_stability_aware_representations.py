"""Tests for stability-aware stream representation generation."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    RepresentationBuilder,
    StabilityAwareRepresentationBuilder,
    StreamProfiler,
    TemporalStreamProfiler,
)

TOPIC = "factory/line1/sensor7"
SNAPSHOT_PROFILER = StreamProfiler()


def _observation(*, tags=None, fields=None, topic=TOPIC):
    return SNAPSHOT_PROFILER.profile(topic, tags or {}, fields or {})


def _update(profiler, previous=None, *, tags=None, fields=None, topic=TOPIC):
    return profiler.update(
        previous.profile if previous is not None else None,
        _observation(tags=tags, fields=fields, topic=topic),
    )


def _repeat(profiler, values, *, source="tag", key="location"):
    state = None
    for value in values:
        kwargs = {f"{source}s": {key: value}}
        state = _update(profiler, state, **kwargs)
    return state


def test_first_categorical_candidate_contributes_key_and_schema_not_value():
    update = _update(TemporalStreamProfiler(3), tags={"location": "room_a"})

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == ""
    assert result.key_only == "location"
    assert result.key_value == "location"
    assert result.schema == "location: string"
    assert "room a" not in result.topic_key_value


def test_stable_categorical_establishment_adds_trusted_value():
    update = _repeat(TemporalStreamProfiler(3), ("room_a",) * 3)

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == "room a"
    assert result.key_value == "location: room a"
    assert result.topic_key_value.endswith("location: room a")


def test_pending_candidate_does_not_replace_existing_stable_value():
    profiler = TemporalStreamProfiler(3)
    stable = _repeat(profiler, ("A", "A", "A"))
    candidate = _update(profiler, stable, tags={"location": "B"})

    result = StabilityAwareRepresentationBuilder().build(candidate.profile)

    assert result.value_only == "A"
    assert result.key_value == "location: A"
    assert "B" not in " | ".join(result.as_dict().values())


def test_stable_replacement_uses_new_value():
    update = _repeat(
        TemporalStreamProfiler(3),
        ("A", "A", "A", "B", "B", "B"),
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == "B"
    assert result.key_value == "location: B"


def test_numeric_field_is_structural_without_raw_literal():
    update = _update(TemporalStreamProfiler(3), fields={"temperature": 22.8})

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == ""
    assert result.key_only == "temperature"
    assert result.key_value == "temperature"
    assert result.schema == "temperature: numeric"
    assert result.numeric_key_only == "temperature"
    assert "22.8" not in " | ".join(result.as_dict().values())


def test_numeric_field_changes_leave_stability_aware_text_unchanged():
    profiler = TemporalStreamProfiler(2)
    first = _update(profiler, fields={"temperature": 22.1})
    second = _update(profiler, first, fields={"temperature": 22.8})

    builder = StabilityAwareRepresentationBuilder()

    assert builder.build(first.profile) == builder.build(second.profile)


def test_stable_numeric_tag_is_literal_except_in_numeric_key_only():
    update = _repeat(
        TemporalStreamProfiler(2),
        (7, 7),
        key="channel",
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == "7"
    assert result.key_value == "channel: 7"
    assert result.numeric_key_only == "channel"


def test_stable_identifier_suppresses_literal_but_preserves_structure():
    update = _repeat(
        TemporalStreamProfiler(2),
        ("TH-991", "TH-991"),
        key="sensor_id",
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == ""
    assert result.key_only == "sensor id"
    assert result.key_value == "sensor id"
    assert result.schema == "sensor id: string"
    assert "TH 991" not in " | ".join(result.as_dict().values())


def test_stable_timestamp_suppresses_literal_but_preserves_structure():
    timestamp = "2026-07-30T12:00:00Z"
    update = _repeat(
        TemporalStreamProfiler(2),
        (timestamp, timestamp),
        key="timestamp",
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == ""
    assert result.key_only == "timestamp"
    assert result.key_value == "timestamp"
    assert result.schema == "timestamp: string"
    assert "2026" not in " | ".join(result.as_dict().values())


def test_stable_unit_value_is_preserved():
    update = _repeat(TemporalStreamProfiler(2), ("C", "C"), key="unit")

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == "C"
    assert result.key_value == "unit: C"
    assert result.numeric_key_only == "unit: C"


def test_transient_missing_entry_remains_included():
    profiler = TemporalStreamProfiler(2)
    stable = _repeat(profiler, ("A", "A"))
    missing_once = _update(profiler, stable)

    result = StabilityAwareRepresentationBuilder(3).build(missing_once.profile)

    assert result.key_value == "location: A"


@pytest.mark.parametrize("missing_count", [3, 4])
def test_persistently_missing_entry_is_excluded(missing_count):
    profiler = TemporalStreamProfiler(2)
    state = _repeat(profiler, ("A", "A"))
    for _ in range(missing_count):
        state = _update(profiler, state)

    result = StabilityAwareRepresentationBuilder(3).build(state.profile)

    assert result.value_only == ""
    assert result.key_only == ""
    assert result.key_value == ""
    assert result.schema == ""
    assert result.numeric_key_only == ""
    assert result.topic_key_value == "factory line1 sensor7"


def test_persistently_missing_entry_is_included_after_reappearance():
    profiler = TemporalStreamProfiler(2)
    state = _repeat(profiler, ("A", "A"))
    for _ in range(3):
        state = _update(profiler, state)
    reappeared = _update(profiler, state, tags={"location": "A"})

    result = StabilityAwareRepresentationBuilder(3).build(reappeared.profile)

    assert result.key_value == "location: A"


def test_entry_order_is_tags_then_fields_and_normalized_key():
    update = _update(
        TemporalStreamProfiler(1),
        tags={"z_tag": "z", "a_tag": "a"},
        fields={"z_field": "z", "a_field": "a"},
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.key_only == "a tag | z tag | a field | z field"


def test_order_does_not_depend_on_input_mapping_order():
    profiler = TemporalStreamProfiler(1)
    first = _update(
        profiler,
        tags={"z_tag": "z", "a_tag": "a"},
        fields={"z_field": "z", "a_field": "a"},
    )
    reversed_update = _update(
        TemporalStreamProfiler(1),
        tags={"a_tag": "a", "z_tag": "z"},
        fields={"a_field": "a", "z_field": "z"},
    )

    builder = StabilityAwareRepresentationBuilder()

    assert builder.build(first.profile) == builder.build(reversed_update.profile)


def test_same_normalized_key_in_tag_and_field_keeps_both_in_source_order():
    update = _update(
        TemporalStreamProfiler(1),
        tags={"status": "tag_value"},
        fields={"status": "field_value"},
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.key_only == "status | status"
    assert result.key_value == "status: tag value | status: field value"


def test_topic_normalization_matches_snapshot_builder():
    profile = _update(
        TemporalStreamProfiler(),
        topic="Factory/Line-1",
    ).profile

    stable = StabilityAwareRepresentationBuilder().build(profile)
    snapshot = RepresentationBuilder().build("Factory/Line-1", {}, {})

    assert stable.topic_key_value == snapshot.topic_key_value == "factory line 1"


def test_empty_trusted_value_set_is_not_filled_with_placeholders():
    update = _update(
        TemporalStreamProfiler(1),
        tags={"device_id": "abc123"},
        fields={"temperature": 22.8},
    )

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert result.value_only == ""


@pytest.mark.parametrize("threshold", [True, False, 0, -1, 1.5, "3", None])
def test_invalid_exclusion_threshold_is_rejected(threshold):
    with pytest.raises(
        ValueError,
        match="missing_observations_before_exclusion must be at least 1",
    ):
        StabilityAwareRepresentationBuilder(threshold)


def test_result_is_immutable_and_profile_is_not_mutated():
    update = _update(TemporalStreamProfiler(1), tags={"location": "A"})
    original_entries = update.profile.entries

    result = StabilityAwareRepresentationBuilder().build(update.profile)

    assert update.profile.entries is original_entries
    assert update.profile.entries[0].stable_value == "A"
    with pytest.raises(FrozenInstanceError):
        result.value_only = "B"


def test_stability_aware_text_is_stable_while_snapshot_values_change():
    profiler = TemporalStreamProfiler(2)
    first = _update(
        profiler,
        tags={"location": "lab"},
        fields={"temperature": 22.1},
    )
    second = _update(
        profiler,
        first,
        tags={"location": "lab"},
        fields={"temperature": 22.8},
    )
    third = _update(
        profiler,
        second,
        tags={"location": "lab"},
        fields={"temperature": 23.4},
    )

    stable_builder = StabilityAwareRepresentationBuilder()
    snapshot_builder = RepresentationBuilder()

    assert stable_builder.build(second.profile) == stable_builder.build(third.profile)
    assert snapshot_builder.build(
        TOPIC, {"location": "lab"}, {"temperature": 22.8}
    ) != snapshot_builder.build(TOPIC, {"location": "lab"}, {"temperature": 23.4})
