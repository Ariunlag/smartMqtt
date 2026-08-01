import argparse
import json

import pytest

from scripts.run_real_stack_acceptance import (
    COMPOSE_FILES,
    RealStackAcceptance,
    validate_run_id,
)


@pytest.mark.parametrize("value", ("run-1", "20260731t235959z", "a" * 32))
def test_acceptance_run_id_allows_only_topic_safe_values(value):
    assert validate_run_id(value) == value


@pytest.mark.parametrize(
    "value",
    ("", "Uppercase", "contains/slash", "contains space", "-leading", "a" * 33),
)
def test_acceptance_run_id_rejects_unsafe_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        validate_run_id(value)


def test_acceptance_composition_is_isolated_without_volume_deletion_commands():
    runner = RealStackAcceptance("safe-run")

    assert runner.prefix == "acceptance/safe-run"
    assert runner.environment["SEMANTIC_PERSISTENCE_STATE_KEY"] == (
        "acceptance-safe-run"
    )
    assert (
        tuple(
            runner._compose_prefix[index + 1]
            for index, value in enumerate(runner._compose_prefix[:-1])
            if value == "-f"
        )
        == COMPOSE_FILES
    )
    assert "down" not in runner._compose_prefix
    assert "-v" not in runner._compose_prefix


def test_acceptance_payload_is_valid_mqtt_contract_and_contains_no_credentials():
    payload = RealStackAcceptance._payload(
        fields={"temperature": 20.0},
        tags={"site": "acceptance"},
    )
    body = json.loads(payload)

    assert body["fields"] == {"temperature": 20.0}
    assert body["tags"] == {"site": "acceptance"}
    assert body["timestamp"].endswith("Z")
    assert "password" not in payload.lower()
    assert "token" not in payload.lower()


def test_candidate_selection_requires_an_exact_isolated_topic_set():
    candidates = [
        {
            "representation_name": "schema",
            "member_topics": ["prefix/a", "prefix/b", "old/topic"],
        },
        {
            "representation_name": "key_value",
            "member_topics": ["prefix/b", "prefix/a"],
        },
    ]

    selected = RealStackAcceptance._candidate_for(candidates, ("prefix/a", "prefix/b"))

    assert selected == candidates[1]
