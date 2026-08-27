from services.store.relation_store import DupeStore


def test_duplicate_pair_ordering_is_utf8_byte_deterministic():
    left = "acceptance/pgvector-check/temperature/sensor-0"
    right = "acceptance/pgvector-check2/temperature/sensor-0"

    assert DupeStore._pair(right, left) == (left, right)
    assert left.encode("utf-8") < right.encode("utf-8")


def test_duplicate_pair_ordering_is_independent_of_input_direction():
    first = "sensor/ä"
    second = "sensor/z"

    assert DupeStore._pair(first, second) == DupeStore._pair(second, first)
