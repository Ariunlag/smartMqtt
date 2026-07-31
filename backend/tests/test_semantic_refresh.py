"""Isolated tests for deterministic semantic refresh decisions."""

from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    SemanticRefreshPolicy,
    SemanticRefreshReasonType,
    StreamProfiler,
    TemporalStreamProfiler,
)

TOPIC = "factory/line1/sensor7"
SNAPSHOT_PROFILER = StreamProfiler()


def _observation(tags=None, fields=None):
    return SNAPSHOT_PROFILER.profile(TOPIC, tags or {}, fields or {})


def _update(profiler, previous=None, *, tags=None, fields=None):
    return profiler.update(
        previous.profile if previous is not None else None,
        _observation(tags, fields),
    )


def _reason_types(decision):
    return tuple(reason.reason_type for reason in decision.reasons)


def test_first_observation_requests_initialization_refresh():
    update = _update(TemporalStreamProfiler(), fields={"temperature": 22.1})

    decision = SemanticRefreshPolicy().evaluate(update)

    assert decision.should_refresh is True
    assert _reason_types(decision) == (SemanticRefreshReasonType.INITIAL_OBSERVATION,)
    assert decision.reasons[0].source is None
    assert decision.reasons[0].normalized_key is None


def test_initial_observation_with_many_keys_has_only_initial_reason():
    update = _update(
        TemporalStreamProfiler(),
        tags={"location": "A", "unit": "C"},
        fields={"temperature": 22.1, "humidity": 60},
    )

    decision = SemanticRefreshPolicy().evaluate(update)

    assert len(update.changes) == 4
    assert _reason_types(decision) == (SemanticRefreshReasonType.INITIAL_OBSERVATION,)


def test_unchanged_repeated_observation_does_not_refresh():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, tags={"location": "A"})
    second = _update(profiler, first, tags={"location": "A"})

    decision = SemanticRefreshPolicy().evaluate(second)

    assert decision.should_refresh is False
    assert decision.reasons == ()


def test_numeric_value_change_alone_does_not_refresh():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, fields={"temperature": 22.1})
    changed = _update(profiler, first, fields={"temperature": 22.8})

    decision = SemanticRefreshPolicy().evaluate(changed)

    assert decision.should_refresh is False
    assert decision.reasons == ()


def test_categorical_value_change_before_hysteresis_does_not_refresh():
    profiler = TemporalStreamProfiler(stable_value_observations=3)
    state = None
    for _ in range(3):
        state = _update(profiler, state, tags={"location": "room_a"})
    candidate = _update(profiler, state, tags={"location": "room_b"})

    decision = SemanticRefreshPolicy().evaluate(candidate)

    assert decision.should_refresh is False
    assert decision.reasons == ()


def test_stable_value_change_triggers_refresh():
    profiler = TemporalStreamProfiler(stable_value_observations=2)
    state = None
    for value in ("room_a", "room_a", "room_b"):
        state = _update(profiler, state, tags={"location": value})
    changed = _update(profiler, state, tags={"location": "room_b"})

    decision = SemanticRefreshPolicy().evaluate(changed)

    assert _reason_types(decision) == (SemanticRefreshReasonType.STABLE_VALUE_CHANGED,)
    assert decision.reasons[0].previous_value == "room a"
    assert decision.reasons[0].current_value == "room b"


def test_type_change_triggers_refresh_with_type_details():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, fields={"reading": 1})
    changed = _update(profiler, first, fields={"reading": "one"})

    decision = SemanticRefreshPolicy().evaluate(changed)

    assert _reason_types(decision) == (SemanticRefreshReasonType.TYPE_CHANGED,)
    reason = decision.reasons[0]
    assert reason.source == "field"
    assert reason.normalized_key == "reading"
    assert reason.previous_value_type == "numeric"
    assert reason.current_value_type == "string"


def test_type_and_value_change_produces_only_type_reason():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, fields={"reading": 1})
    changed = _update(profiler, first, fields={"reading": "one"})

    assert len(changed.changes) == 2
    decision = SemanticRefreshPolicy().evaluate(changed)

    assert _reason_types(decision) == (SemanticRefreshReasonType.TYPE_CHANGED,)


def test_key_added_after_initialization_triggers_refresh():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, tags={"location": "A"})
    changed = _update(
        profiler,
        first,
        tags={"location": "A", "vendor": "Acme"},
    )

    decision = SemanticRefreshPolicy().evaluate(changed)

    assert _reason_types(decision) == (SemanticRefreshReasonType.KEY_ADDED,)
    assert decision.reasons[0].normalized_key == "vendor"
    assert decision.reasons[0].current_value == "Acme"


def test_first_missing_observation_below_threshold_does_not_refresh():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, tags={"location": "A"})
    missing = _update(profiler, first)

    decision = SemanticRefreshPolicy(3).evaluate(missing)

    assert decision.should_refresh is False


def test_missing_streak_below_threshold_continues_without_refresh():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, tags={"location": "A"})
    missing_once = _update(profiler, first)
    missing_twice = _update(profiler, missing_once)

    decision = SemanticRefreshPolicy(3).evaluate(missing_twice)

    assert decision.should_refresh is False
    assert decision.reasons == ()


def test_missing_streak_at_threshold_triggers_once():
    profiler = TemporalStreamProfiler()
    state = _update(profiler, tags={"location": "A"})
    for _ in range(3):
        state = _update(profiler, state)

    decision = SemanticRefreshPolicy(3).evaluate(state)

    assert _reason_types(decision) == (SemanticRefreshReasonType.KEY_MISSING_PERSISTED,)
    assert decision.reasons[0].source == "tag"
    assert decision.reasons[0].normalized_key == "location"
    assert decision.reasons[0].previous_value == "A"


def test_continued_absence_beyond_threshold_does_not_repeat_refresh():
    profiler = TemporalStreamProfiler()
    state = _update(profiler, tags={"location": "A"})
    for _ in range(4):
        state = _update(profiler, state)

    decision = SemanticRefreshPolicy(3).evaluate(state)

    assert decision.should_refresh is False
    assert decision.reasons == ()


def test_reappearance_resets_missing_threshold_behavior():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, tags={"location": "A"})
    missing = _update(profiler, first)
    reappeared = _update(profiler, missing, tags={"location": "A"})
    missing_again = _update(profiler, reappeared)

    decision = SemanticRefreshPolicy(2).evaluate(missing_again)

    assert decision.should_refresh is False
    second_missing = _update(profiler, missing_again)
    assert _reason_types(SemanticRefreshPolicy(2).evaluate(second_missing)) == (
        SemanticRefreshReasonType.KEY_MISSING_PERSISTED,
    )


def test_multiple_strong_reasons_preserve_temporal_order():
    profiler = TemporalStreamProfiler(stable_value_observations=2)
    first = _update(
        profiler,
        tags={"location": "A"},
        fields={"reading": 1},
    )
    stable = _update(
        profiler,
        first,
        tags={"location": "A"},
        fields={"reading": 2},
    )
    candidate = _update(
        profiler,
        stable,
        tags={"location": "B"},
        fields={"reading": 3},
    )
    changed = _update(
        profiler,
        candidate,
        tags={"location": "B"},
        fields={"reading": "three"},
    )

    decision = SemanticRefreshPolicy().evaluate(changed)

    assert [
        (reason.reason_type, reason.source, reason.normalized_key)
        for reason in decision.reasons
    ] == [
        (SemanticRefreshReasonType.STABLE_VALUE_CHANGED, "tag", "location"),
        (SemanticRefreshReasonType.TYPE_CHANGED, "field", "reading"),
    ]


def test_tag_and_field_same_normalized_key_have_distinct_reasons():
    profiler = TemporalStreamProfiler()
    first = _update(profiler)
    changed = _update(
        profiler,
        first,
        tags={"status": "online"},
        fields={"status": "active"},
    )

    decision = SemanticRefreshPolicy().evaluate(changed)

    assert [
        (reason.reason_type, reason.source, reason.normalized_key)
        for reason in decision.reasons
    ] == [
        (SemanticRefreshReasonType.KEY_ADDED, "tag", "status"),
        (SemanticRefreshReasonType.KEY_ADDED, "field", "status"),
    ]


@pytest.mark.parametrize("threshold", [True, False, 0, -1, 1.5, "3", None])
def test_invalid_missing_threshold_is_rejected(threshold):
    with pytest.raises(
        ValueError,
        match="missing_observations_before_refresh must be at least 1",
    ):
        SemanticRefreshPolicy(threshold)


def test_decision_and_reason_are_immutable():
    update = _update(TemporalStreamProfiler(), tags={"location": "A"})
    decision = SemanticRefreshPolicy().evaluate(update)

    with pytest.raises(FrozenInstanceError):
        decision.should_refresh = False
    with pytest.raises(FrozenInstanceError):
        decision.reasons[0].reason_type = SemanticRefreshReasonType.KEY_ADDED


def test_evaluate_does_not_mutate_temporal_update():
    profiler = TemporalStreamProfiler()
    first = _update(profiler, fields={"reading": 1})
    changed = _update(profiler, first, fields={"reading": "one"})
    original_profile = changed.profile
    original_changes = changed.changes

    SemanticRefreshPolicy().evaluate(changed)

    assert changed.profile is original_profile
    assert changed.changes is original_changes
