"""Isolated tests for deterministic temporal stream profiling."""

from dataclasses import FrozenInstanceError

import pytest
from services.class_recommendation.profiling import StreamProfiler
from services.class_recommendation.temporal import (
    TemporalChangeType,
    TemporalStreamProfiler,
)

TOPIC = "factory/line1/sensor7"
SNAPSHOT_PROFILER = StreamProfiler()


def _observation(tags=None, fields=None):
    return SNAPSHOT_PROFILER.profile(TOPIC, tags or {}, fields or {})


def _state(profile, source, normalized_key):
    return next(
        entry
        for entry in profile.entries
        if entry.source == source and entry.normalized_key == normalized_key
    )


def _change_types(update):
    return tuple(change.change_type for change in update.changes)


def test_first_observation_creates_state_and_key_added_events():
    update = TemporalStreamProfiler(3).update(
        None,
        _observation(
            tags={"location": "Warehouse_01"},
            fields={"temp": 22.5},
        ),
    )

    assert update.profile.topic == TOPIC
    assert update.profile.observation_count == 1
    assert [
        (entry.source, entry.normalized_key) for entry in update.profile.entries
    ] == [("tag", "location"), ("field", "temp")]
    assert _change_types(update) == (
        TemporalChangeType.KEY_ADDED,
        TemporalChangeType.KEY_ADDED,
    )
    location = _state(update.profile, "tag", "location")
    assert location.observation_count == 1
    assert location.present_count == 1
    assert location.missing_streak == 0
    assert location.candidate_value == "Warehouse 01"
    assert location.candidate_streak == 1


def test_repeated_unchanged_tag_does_not_report_value_changed():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(tags={"location": "A"}))
    second = profiler.update(
        first.profile,
        _observation(tags={"location": "A"}),
    )

    assert TemporalChangeType.VALUE_CHANGED not in _change_types(second)
    assert TemporalChangeType.STABLE_VALUE_ESTABLISHED not in _change_types(second)
    location = _state(second.profile, "tag", "location")
    assert location.value_change_count == 0
    assert location.present_count == 2
    assert location.candidate_streak == 2


def test_first_stable_value_establishment_emits_explicit_evidence():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(tags={"location": "A"}))
    second = profiler.update(first.profile, _observation(tags={"location": "A"}))

    established = profiler.update(
        second.profile,
        _observation(tags={"location": "A"}),
    )

    assert _change_types(established) == (TemporalChangeType.STABLE_VALUE_ESTABLISHED,)
    assert established.changes[0].previous_value is None
    assert established.changes[0].current_value == "A"


def test_tag_value_transition_reports_value_changed():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(tags={"location": "A"}))

    second = profiler.update(
        first.profile,
        _observation(tags={"location": "B"}),
    )

    assert _change_types(second) == (TemporalChangeType.VALUE_CHANGED,)
    change = second.changes[0]
    assert change.previous_value == "A"
    assert change.current_value == "B"
    assert _state(second.profile, "tag", "location").value_change_count == 1


def test_transient_value_does_not_replace_stable_value():
    profiler = TemporalStreamProfiler(3)
    state = None
    for _ in range(3):
        state = profiler.update(
            state.profile if state else None,
            _observation(tags={"location": "A"}),
        )

    transient = profiler.update(
        state.profile,
        _observation(tags={"location": "B"}),
    )
    location = _state(transient.profile, "tag", "location")

    assert location.stable_value == "A"
    assert location.candidate_value == "B"
    assert location.candidate_streak == 1
    assert TemporalChangeType.STABLE_VALUE_CHANGED not in _change_types(transient)


def test_persistent_candidate_emits_stable_value_changed():
    profiler = TemporalStreamProfiler(3)
    state = None
    for value in ("A", "A", "A", "B", "B"):
        state = profiler.update(
            state.profile if state else None,
            _observation(tags={"location": value}),
        )

    changed = profiler.update(
        state.profile,
        _observation(tags={"location": "B"}),
    )
    location = _state(changed.profile, "tag", "location")

    assert location.stable_value == "B"
    assert location.candidate_value is None
    assert location.candidate_streak == 0
    assert _change_types(changed) == (TemporalChangeType.STABLE_VALUE_CHANGED,)
    assert TemporalChangeType.STABLE_VALUE_ESTABLISHED not in _change_types(changed)
    assert changed.changes[0].previous_value == "A"
    assert changed.changes[0].current_value == "B"


def test_candidate_streak_resets_when_candidate_changes():
    profiler = TemporalStreamProfiler(3)
    state = None
    for value in ("A", "A", "A", "B", "B", "C"):
        state = profiler.update(
            state.profile if state else None,
            _observation(tags={"location": value}),
        )

    location = _state(state.profile, "tag", "location")
    assert location.stable_value == "A"
    assert location.candidate_value == "C"
    assert location.candidate_streak == 1


def test_numeric_field_changes_do_not_establish_stable_categorical_value():
    profiler = TemporalStreamProfiler(2)
    state = None
    changes = []
    for value in (22.1, 22.4, 22.8):
        state = profiler.update(
            state.profile if state else None,
            _observation(fields={"temperature": value}),
        )
        changes.extend(state.changes)

    temperature = _state(state.profile, "field", "temperature")
    assert temperature.value_change_count == 2
    assert temperature.stable_value is None
    assert temperature.candidate_value is None
    assert temperature.candidate_streak == 0
    assert all(
        change.change_type
        not in {
            TemporalChangeType.STABLE_VALUE_ESTABLISHED,
            TemporalChangeType.STABLE_VALUE_CHANGED,
        }
        for change in changes
    )


def test_numeric_tag_can_establish_stable_metadata_value():
    profiler = TemporalStreamProfiler(2)
    first = profiler.update(None, _observation(tags={"channel": 7}))
    second = profiler.update(
        first.profile,
        _observation(tags={"channel": 7}),
    )

    channel = _state(second.profile, "tag", "channel")
    assert channel.is_numeric is True
    assert channel.stable_value == "7"


def test_type_change_is_counted_and_emitted():
    profiler = TemporalStreamProfiler(2)
    first = profiler.update(None, _observation(fields={"reading": 1}))

    changed = profiler.update(
        first.profile,
        _observation(fields={"reading": "1"}),
    )
    reading = _state(changed.profile, "field", "reading")

    assert reading.current_value_type == "string"
    assert reading.type_change_count == 1
    assert _change_types(changed) == (TemporalChangeType.TYPE_CHANGED,)
    assert changed.changes[0].previous_value_type == "numeric"
    assert changed.changes[0].current_value_type == "string"


def test_newly_appearing_key_produces_key_added():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(tags={"location": "A"}))

    changed = profiler.update(
        first.profile,
        _observation(tags={"location": "A", "vendor": "Acme"}),
    )

    assert _change_types(changed) == (TemporalChangeType.KEY_ADDED,)
    assert changed.changes[0].normalized_key == "vendor"


def test_new_key_with_immediate_stability_emits_only_key_added():
    profiler = TemporalStreamProfiler(1)
    first = profiler.update(None, _observation())

    added = profiler.update(
        first.profile,
        _observation(tags={"location": "A"}),
    )

    assert _change_types(added) == (TemporalChangeType.KEY_ADDED,)
    assert _state(added.profile, "tag", "location").stable_value == "A"


def test_missing_key_tracks_streak_and_emits_evidence():
    profiler = TemporalStreamProfiler(2)
    first = profiler.update(None, _observation(tags={"location": "A"}))
    missing_once = profiler.update(first.profile, _observation())
    missing_twice = profiler.update(missing_once.profile, _observation())

    assert _change_types(missing_once) == (TemporalChangeType.KEY_MISSING,)
    assert _change_types(missing_twice) == (TemporalChangeType.KEY_MISSING,)
    location = _state(missing_twice.profile, "tag", "location")
    assert location.observation_count == 3
    assert location.present_count == 1
    assert location.missing_streak == 2


def test_reappearing_key_resets_missing_streak():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(tags={"location": "A"}))
    missing = profiler.update(first.profile, _observation())

    reappeared = profiler.update(
        missing.profile,
        _observation(tags={"location": "A"}),
    )

    location = _state(reappeared.profile, "tag", "location")
    assert location.missing_streak == 0
    assert location.present_count == 2
    assert _change_types(reappeared) == (TemporalChangeType.KEY_REAPPEARED,)
    assert reappeared.changes[0].previous_missing_streak == 1


def test_reappearance_with_changed_value_preserves_event_order():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(tags={"location": "A"}))
    missing = profiler.update(first.profile, _observation())

    reappeared = profiler.update(
        missing.profile,
        _observation(tags={"location": "B"}),
    )

    assert _change_types(reappeared) == (
        TemporalChangeType.KEY_REAPPEARED,
        TemporalChangeType.VALUE_CHANGED,
    )


def test_reappearance_with_type_and_value_change_has_deterministic_order():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(None, _observation(fields={"reading": 1}))
    missing = profiler.update(first.profile, _observation())

    reappeared = profiler.update(
        missing.profile,
        _observation(fields={"reading": "one"}),
    )

    assert _change_types(reappeared) == (
        TemporalChangeType.KEY_REAPPEARED,
        TemporalChangeType.TYPE_CHANGED,
        TemporalChangeType.VALUE_CHANGED,
    )
    assert reappeared.changes[0].previous_missing_streak == 1


def test_tag_and_field_reappearance_identities_remain_distinct():
    profiler = TemporalStreamProfiler(3)
    first = profiler.update(
        None,
        _observation(tags={"status": "online"}, fields={"status": "active"}),
    )
    missing = profiler.update(first.profile, _observation())

    reappeared = profiler.update(
        missing.profile,
        _observation(tags={"status": "online"}, fields={"status": "active"}),
    )

    assert [
        (change.change_type, change.source, change.normalized_key)
        for change in reappeared.changes
    ] == [
        (TemporalChangeType.KEY_REAPPEARED, "tag", "status"),
        (TemporalChangeType.KEY_REAPPEARED, "field", "status"),
    ]


def test_same_normalized_key_in_tag_and_field_remains_separate():
    update = TemporalStreamProfiler(2).update(
        None,
        _observation(tags={"status": "online"}, fields={"status": "active"}),
    )

    tag_state = _state(update.profile, "tag", "status")
    field_state = _state(update.profile, "field", "status")
    assert tag_state.last_normalized_value == "online"
    assert field_state.last_normalized_value == "active"
    assert len(update.profile.entries) == 2


def test_temporal_state_preserves_structural_flags():
    update = TemporalStreamProfiler(2).update(
        None,
        _observation(
            tags={
                "device_id": "abc123",
                "timestamp": "2026-07-30T12:00:00Z",
            }
        ),
    )

    device = _state(update.profile, "tag", "device id")
    timestamp = _state(update.profile, "tag", "timestamp")
    assert device.is_identifier_like is True
    assert timestamp.is_timestamp_like is True


def test_change_and_state_order_is_deterministic():
    observation = _observation(
        tags={"z_tag": "z", "a_tag": "a"},
        fields={"z_field": 1, "a_field": 2},
    )
    reversed_observation = _observation(
        tags={"a_tag": "a", "z_tag": "z"},
        fields={"a_field": 2, "z_field": 1},
    )

    update = TemporalStreamProfiler(2).update(None, observation)
    reversed_update = TemporalStreamProfiler(2).update(
        None,
        reversed_observation,
    )
    identities = [
        (entry.source, entry.normalized_key) for entry in update.profile.entries
    ]
    change_identities = [
        (change.source, change.normalized_key) for change in update.changes
    ]

    expected = [
        ("tag", "a tag"),
        ("tag", "z tag"),
        ("field", "a field"),
        ("field", "z field"),
    ]
    assert identities == expected
    assert change_identities == expected
    assert reversed_update == update


def test_observation_is_not_mutated_and_results_are_immutable():
    observation = _observation(tags={"location": "A"})
    original_entries = observation.entries

    update = TemporalStreamProfiler(2).update(None, observation)

    assert observation.entries is original_entries
    assert observation.entries[0].normalized_value == "A"
    with pytest.raises(FrozenInstanceError):
        update.profile.observation_count = 2
    with pytest.raises(FrozenInstanceError):
        update.profile.entries[0].missing_streak = 1
    with pytest.raises(FrozenInstanceError):
        update.changes[0].current_value = "B"


def test_reappearance_change_diagnostics_are_immutable():
    profiler = TemporalStreamProfiler(2)
    first = profiler.update(None, _observation(tags={"location": "A"}))
    missing = profiler.update(first.profile, _observation())
    reappeared = profiler.update(
        missing.profile,
        _observation(tags={"location": "A"}),
    )

    with pytest.raises(FrozenInstanceError):
        reappeared.changes[0].previous_missing_streak = 2
