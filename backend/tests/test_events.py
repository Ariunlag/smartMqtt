"""Unit tests for the versioned WebSocket event envelope (issue #8)."""

from services.events import EVENT_SCHEMA_VERSION, make_envelope


def test_envelope_has_all_required_fields():
    env = make_envelope("duplicate", {"topics": ["a", "b"]})
    assert set(env) == {"version", "event_id", "event_type", "occurred_at", "data"}
    assert env["version"] == EVENT_SCHEMA_VERSION
    assert env["event_type"] == "duplicate"
    assert env["data"] == {"topics": ["a", "b"]}


def test_envelope_generates_unique_event_ids():
    a = make_envelope("x", 1)
    b = make_envelope("x", 1)
    assert a["event_id"] != b["event_id"]


def test_envelope_occurred_at_is_iso_utc():
    env = make_envelope("x", 1)
    # ISO-8601 with a time component
    assert "T" in env["occurred_at"]


def test_envelope_accepts_explicit_id_and_timestamp():
    env = make_envelope(
        "x", 1, event_id="fixed", occurred_at="2024-01-01T00:00:00+00:00"
    )
    assert env["event_id"] == "fixed"
    assert env["occurred_at"] == "2024-01-01T00:00:00+00:00"
