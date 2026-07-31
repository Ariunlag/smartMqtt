"""Unit tests for dependency-free stream profiling and representations."""

from services.semantic import (
    RepresentationBuilder,
    StreamProfiler,
    normalize_text,
)

CASE_1_TOPIC = "factory/line1/sensor7"
CASE_1_TAGS = {
    "location": "Warehouse_01",
    "sensor_id": "TH-991",
    "vendor": "Acme",
}
CASE_1_FIELDS = {
    "temp": 22.5,
    "humidity": 61,
    "active": True,
}


def _by_key(profile):
    return {entry.key: entry for entry in profile.entries}


def test_case_1_profiles_numeric_boolean_identifier_and_normalization():
    profile = StreamProfiler().profile(CASE_1_TOPIC, CASE_1_TAGS, CASE_1_FIELDS)
    entries = _by_key(profile)

    assert entries["temp"].value_type == "numeric"
    assert entries["temp"].is_numeric is True
    assert entries["temp"].normalized_value == "22.5"
    assert entries["temp"].source == "field"
    assert entries["humidity"].is_numeric is True
    assert entries["active"].value_type == "boolean"
    assert entries["active"].is_numeric is False
    assert entries["sensor_id"].is_identifier_like is True
    assert entries["sensor_id"].source == "tag"
    assert entries["sensor_id"].normalized_key == "sensor id"
    assert entries["sensor_id"].normalized_value == "TH 991"
    assert entries["location"].normalized_value == "Warehouse 01"


def test_case_1_builds_all_six_representations():
    result = RepresentationBuilder().build(
        CASE_1_TOPIC,
        CASE_1_TAGS,
        CASE_1_FIELDS,
    )

    assert result.as_dict() == {
        "value_only": "Warehouse 01 | TH 991 | Acme | true | 61 | 22.5",
        "key_only": "location | sensor id | vendor | active | humidity | temp",
        "key_value": (
            "location: Warehouse 01 | sensor id: TH 991 | vendor: Acme | "
            "active: true | humidity: 61 | temp: 22.5"
        ),
        "schema": (
            "location: string | sensor id: string | vendor: string | "
            "active: boolean | humidity: numeric | temp: numeric"
        ),
        "numeric_key_only": (
            "location: Warehouse 01 | sensor id: TH 991 | vendor: Acme | "
            "active: true | humidity | temp"
        ),
        "topic_key_value": (
            "factory line1 sensor7 | location: Warehouse 01 | "
            "sensor id: TH 991 | vendor: Acme | active: true | "
            "humidity: 61 | temp: 22.5"
        ),
    }


def test_timestamp_unit_and_identifier_heuristics_are_key_based():
    profile = StreamProfiler().profile(
        "devices/example",
        {
            "timestamp": "2026-07-30T12:00:00Z",
            "unit": "C",
            "device_id": "abc123",
        },
        {},
    )
    entries = _by_key(profile)

    assert entries["timestamp"].is_timestamp_like is True
    assert entries["timestamp"].normalized_value == "2026 07 30T12:00:00Z"
    assert entries["unit"].is_unit_like is True
    assert entries["device_id"].is_identifier_like is True

    assert entries["unit"].is_timestamp_like is False
    assert entries["device_id"].is_unit_like is False


def test_null_nested_object_and_array_are_profiled_safely():
    fields = {
        "missing": None,
        "metadata": {"z": 2, "a": {"enabled": True}},
        "samples": [1, {"b": 2, "a": 1}, None],
    }

    profile = StreamProfiler().profile("nested/topic", {}, fields)
    entries = _by_key(profile)

    assert entries["missing"].value_type == "null"
    assert entries["missing"].normalized_value == "null"
    assert entries["metadata"].value_type == "object"
    assert entries["metadata"].normalized_value == ('{"a": {"enabled": true}, "z": 2}')
    assert entries["samples"].value_type == "array"
    assert entries["samples"].normalized_value == ('[1, {"a": 1, "b": 2}, null]')

    result = RepresentationBuilder().build("nested/topic", {}, fields)
    assert "metadata: object" in result.schema
    assert "samples: array" in result.schema


def test_profiles_and_representations_do_not_depend_on_mapping_insertion_order():
    tags_a = {"vendor": "Acme", "location": "Warehouse_01", "unit": "C"}
    tags_b = {"unit": "C", "location": "Warehouse_01", "vendor": "Acme"}
    fields_a = {"temp": 22.5, "active": True, "humidity": 61}
    fields_b = {"humidity": 61, "temp": 22.5, "active": True}

    profiler = StreamProfiler()
    builder = RepresentationBuilder(profiler)

    assert profiler.profile("a/b", tags_a, fields_a) == profiler.profile(
        "a/b", tags_b, fields_b
    )
    assert builder.build("a/b", tags_a, fields_a) == builder.build(
        "a/b", tags_b, fields_b
    )


def test_numeric_key_only_omits_numbers_and_preserves_non_numeric_values():
    result = RepresentationBuilder().build(
        "factory/sensor",
        {"location": "Warehouse_01"},
        {
            "temp": 22.5,
            "humidity": 61,
            "status": "active",
            "enabled": False,
        },
    )

    assert result.numeric_key_only == (
        "location: Warehouse 01 | enabled: false | humidity | status: active | temp"
    )
    assert "22.5" not in result.numeric_key_only
    assert "61" not in result.numeric_key_only
    assert "active" in result.numeric_key_only
    assert "false" in result.numeric_key_only


def test_normalization_is_reusable_safe_and_interpretable():
    assert normalize_text("  Sensor_ID--Primary  ", lowercase=True) == (
        "sensor id primary"
    )
    assert normalize_text(True) == "true"
    assert normalize_text(12.5) == "12.5"


def test_empty_message_has_empty_candidates_and_normalized_topic():
    result = RepresentationBuilder().build("Factory/Line-1", {}, {})

    assert result.value_only == ""
    assert result.key_only == ""
    assert result.key_value == ""
    assert result.schema == ""
    assert result.numeric_key_only == ""
    assert result.topic_key_value == "factory line 1"
