import argparse
import json
from pathlib import Path

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
    assert runner.environment["CLASS_RECOMMENDATION_QUEUE_MAXSIZE"] == "128"
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


def test_acceptance_runner_has_no_destructive_compose_or_volume_commands():
    source = (
        Path(__file__).parents[2] / "scripts/run_real_stack_acceptance.py"
    ).read_text(encoding="utf-8")

    assert '"down"' not in source
    assert '"-v"' not in source
    assert "volume rm" not in source
    assert "docker volume" not in source
