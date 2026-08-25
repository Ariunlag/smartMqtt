"""Run the destructive-free SmartMQTT real-stack acceptance workflow.

The runner intentionally uses only the Python standard library and the Docker
Compose CLI. It never deletes volumes or reads TEST benchmark data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.acceptance.yml")
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class AcceptanceFailure(RuntimeError):
    """A bounded acceptance assertion failed with actionable context."""


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz").lower()


def validate_run_id(value: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("run ID must match [a-z0-9][a-z0-9-]{0,31}")
    return value


@dataclass
class AcceptanceReport:
    run_id: str
    topic_prefix: str
    phases: list[str] = field(default_factory=list)
    classification: dict[str, Any] | None = None
    backpressure: dict[str, int] | None = None
    final_generation: int | None = None
    duplicate_identity: dict[str, str] | None = None

    def passed(self, phase: str) -> None:
        self.phases.append(phase)
        print(f"PASS {phase}", flush=True)


class RealStackAcceptance:
    def __init__(self, run_id: str, *, timeout: float = 120.0) -> None:
        self.run_id = validate_run_id(run_id)
        self.timeout = timeout
        self.prefix = f"acceptance/{run_id}"
        self.api = "http://localhost:8000/api"
        self.frontend = "http://localhost:3000/"
        self.report = AcceptanceReport(run_id, self.prefix)
        self.environment = os.environ.copy()
        self.environment["SEMANTIC_PERSISTENCE_STATE_KEY"] = f"acceptance-{run_id}"
        self._compose_prefix = ["docker", "compose"]
        for filename in COMPOSE_FILES:
            self._compose_prefix.extend(("-f", filename))

    def run(self) -> AcceptanceReport:
        try:
            self._start_stack()
            self._subscribe_and_verify_primary_path()
            group_a, group_b = self._discover_and_review()
            self._verify_strict_classification(group_a)
            self._verify_duplicate_identity()
            self._verify_restart_recovery()
            self._verify_broker_recovery()
            self._verify_postgres_recovery(group_b)
            self._verify_backpressure()
            self._verify_bounded_shutdown_and_final_flush()
            self.report.passed("complete real-stack acceptance")
            return self.report
        except Exception as exc:
            diagnostics = self._diagnostics()
            raise AcceptanceFailure(f"{exc}\n\n{diagnostics}") from exc

    # ---- stack lifecycle -------------------------------------------------

    def _start_stack(self) -> None:
        self._compose("build", "backend", "migrate", "frontend", timeout=900)
        self._compose("up", "-d", "postgres", "qdrant", "influxdb", "mqtt")
        for service in ("postgres", "qdrant", "influxdb", "mqtt"):
            self._wait(
                f"{service} container health",
                lambda service=service: self._container_healthy(service),
            )
        self._compose("run", "--rm", "migrate", timeout=180)
        self._compose("up", "-d", "--no-deps", "backend", "frontend")
        self._wait_ready()
        self._wait("frontend availability", lambda: self._url_ok(self.frontend))
        self.report.passed("migration and full Compose startup")

    def _wait_ready(self) -> None:
        self._wait(
            "backend readiness",
            lambda: self._http_status(f"{self.api}/health/ready") == 200,
            timeout=max(self.timeout, 300.0),
        )

    def _container_healthy(self, service: str) -> bool:
        container_id = self._compose_output("ps", "-q", service).strip()
        if not container_id:
            return False
        result = self._run_command(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container_id,
            ],
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() in {
            "healthy",
            "running",
        }

    # ---- primary path ----------------------------------------------------

    def _subscribe_and_verify_primary_path(self) -> None:
        wildcard = f"{self.prefix}/#"
        response = self._json_request(
            "POST", f"{self.api}/subscribe", {"topic": wildcard}
        )
        self._require(response.get("status") == "subscribed", "subscription failed")
        topics = self._json_request("GET", f"{self.api}/topics")["topics"]
        self._require(wildcard in topics, "wildcard subscription was not stored")

        topic = f"{self.prefix}/smoke"
        baseline = self._processing_status()["processed_count"]
        self._publish(topic, fields={"reading": 21.5}, tags={"site": "acceptance"})
        self._wait_influx(topic)
        self._wait_processing_total(baseline + 1)
        self.report.passed("API subscription, real MQTT publish, and Influx write")

    # ---- discovery and review -------------------------------------------

    def _discover_and_review(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        baseline = self._processing_status()["processed_count"]
        group_a = tuple(f"{self.prefix}/temperature/{index}" for index in range(3))
        group_b = tuple(f"{self.prefix}/pressure/{index}" for index in range(3))
        for topic in group_a:
            self._publish(
                topic,
                fields={"temperature": 20.0},
                tags={"kind": "temperature", "site": "acceptance"},
            )
        for topic in group_b:
            self._publish(
                topic,
                fields={"pressure": 900.0},
                tags={"kind": "pressure", "site": "acceptance"},
            )
        self._wait_processing_total(baseline + 6, timeout=240)

        candidates = self._wait_for_candidates(group_a, group_b)
        candidate_a = self._candidate_for(candidates, group_a)
        candidate_b = self._candidate_for(candidates, group_b)
        self._require(
            candidate_a is not None, "temperature candidate was not discovered"
        )
        self._require(candidate_b is not None, "pressure candidate was not discovered")

        review = self._review_payload(
            candidate_a,
            class_id=f"acceptance-{self.run_id}-temperature",
            class_name=f"Acceptance {self.run_id} temperature",
            kept=group_a[:2],
            removed=group_a[2:],
        )
        result = self._json_request(
            "POST", f"{self.api}/semantic-review/reviews", review
        )
        self._require(
            result.get("registry_updated") is True, "review did not publish class"
        )
        self._require(
            len(result.get("prototypes", ())) == 6,
            "review did not create all six prototypes",
        )
        topic_states = self._json_request(
            "GET", f"{self.api}/semantic-review/topic-states"
        )["topics"]
        states_by_topic = {item["topic"]: item for item in topic_states}
        expected_class_id = f"acceptance-{self.run_id}-temperature"
        for topic in group_a[:2]:
            reviewed_state = states_by_topic.get(topic)
            self._require(
                reviewed_state is not None
                and reviewed_state["state"] == "KNOWN"
                and reviewed_state["source"] == "HUMAN"
                and reviewed_state["class_id"] == expected_class_id,
                f"human-confirmed membership did not take precedence: {reviewed_state}",
            )
        self._wait_persistence_clean()
        self.report.passed("UNKNOWN discovery, review, and HUMAN_CONFIRMED precedence")
        return group_a, group_b

    def _wait_for_candidates(
        self, group_a: tuple[str, ...], group_b: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def predicate() -> bool:
            nonlocal found
            body = self._json_request("GET", f"{self.api}/semantic-review/candidates")
            found = body["candidates"]
            return (
                self._candidate_for(found, group_a) is not None
                and self._candidate_for(found, group_b) is not None
            )

        self._wait("two disjoint discovery candidates", predicate, timeout=240)
        return found

    @staticmethod
    def _candidate_for(
        candidates: list[dict[str, Any]], topics: tuple[str, ...]
    ) -> dict[str, Any] | None:
        expected = set(topics)
        matches = [
            candidate
            for candidate in candidates
            if set(candidate["member_topics"]) == expected
        ]
        return (
            min(matches, key=lambda item: item["representation_name"])
            if matches
            else None
        )

    @staticmethod
    def _review_payload(
        candidate: dict[str, Any],
        *,
        class_id: str,
        class_name: str,
        kept: tuple[str, ...],
        removed: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "identity": {
                "representation_name": candidate["representation_name"],
                "member_topics": candidate["member_topics"],
            },
            "class_id": class_id,
            "semantic_class_name": class_name,
            "kept_topics": kept,
            "removed_topics": removed,
            "added_topics": [],
        }

    def _verify_strict_classification(self, group_a: tuple[str, ...]) -> None:
        topic = f"{self.prefix}/temperature/subsequent"
        baseline = self._processing_status()["processed_count"]
        self._publish(
            topic,
            fields={"temperature": 20.0},
            tags={"kind": "temperature", "site": "acceptance"},
        )
        self._wait_processing_total(baseline + 1, timeout=180)

        state: dict[str, Any] | None = None

        def classified() -> bool:
            nonlocal state
            states = self._json_request(
                "GET", f"{self.api}/semantic-review/topic-states"
            )["topics"]
            state = next((item for item in states if item["topic"] == topic), None)
            return state is not None

        self._wait("subsequent strict-threshold decision", classified)
        assert state is not None
        self._require(
            state["state"] in {"KNOWN", "UNCERTAIN"},
            f"reviewed prototype did not become the top class: {state}",
        )
        self._require(
            state["class_id"] == f"acceptance-{self.run_id}-temperature",
            f"unexpected strict-threshold class candidate: {state}",
        )
        self.report.classification = state
        self.report.passed(f"strict frozen-threshold classification ({state['state']})")

    # ---- duplicate identity --------------------------------------------

    def _verify_duplicate_identity(self) -> None:
        canonical = f"{self.prefix}/duplicate/canonical"
        alias = f"{self.prefix}/duplicate/alias"
        keep_a = f"{self.prefix}/keep/a"
        keep_b = f"{self.prefix}/keep/b"
        baseline = self._processing_status()["processed_count"]
        for topic in (canonical, alias, keep_a, keep_b):
            self._publish(
                topic,
                fields={"reading": 42.0},
                tags={"identity": "duplicate-phase", "site": self.run_id},
            )
        self._wait_processing_total(baseline + 4, timeout=240)

        self._insert_pending_pair(canonical, alias)
        self._insert_pending_pair(keep_a, keep_b)
        confirmed = self._json_request(
            "POST",
            f"{self.api}/duplicate-confirm",
            {
                "topics": [canonical, alias],
                "action": "UNSUBSCRIBE",
                "target": alias,
            },
        )
        self._require(
            confirmed["status"] == "CONFIRMED_DUPLICATE",
            "duplicate confirmation did not become terminal",
        )
        kept = self._json_request(
            "POST",
            f"{self.api}/duplicate-confirm",
            {"topics": [keep_a, keep_b], "action": "KEEP_BOTH", "target": None},
        )
        self._require(kept["status"] == "NOT_DUPLICATE", "KEEP_BOTH failed")

        identity = self._json_request(
            "GET", f"{self.api}/duplicate-identity/{urllib.parse.quote(alias, safe='')}"
        )
        self._require(
            identity
            == {
                "topic": alias,
                "canonical_topic": canonical,
                "state": "DUPLICATE_ALIAS",
            },
            f"unexpected canonical identity: {identity}",
        )
        pending = self._json_request("GET", f"{self.api}/duplicates")["duplicates"]
        pending_keys = {tuple(sorted(item["topics"])) for item in pending}
        self._require(
            tuple(sorted((canonical, alias))) not in pending_keys
            and tuple(sorted((keep_a, keep_b))) not in pending_keys,
            "resolved duplicate pair remained pending",
        )
        states = self._json_request("GET", f"{self.api}/semantic-review/topic-states")[
            "topics"
        ]
        state_topics = {item["topic"] for item in states}
        self._require(alias not in state_topics, "alias remained semantic evidence")
        self._require(
            {keep_a, keep_b}.issubset(state_topics),
            "KEEP_BOTH topics stopped being semantic eligible",
        )

        groups = self._json_request("GET", f"{self.api}/groups")["sets"]
        relevant_topics: set[str] = set()
        for group in groups:
            topics = self._json_request(
                "GET", f"{self.api}/groups/{group['id']}/topics"
            )["topics"]
            if canonical in topics or alias in topics:
                relevant_topics.update(topics)
        self._require(
            alias not in relevant_topics, "alias independently counted in group"
        )

        after_confirmation = self._processing_status()["processed_count"]
        self._publish(
            alias,
            fields={"reading": 43.0},
            tags={"identity": "duplicate-phase", "site": self.run_id},
        )
        time.sleep(3)
        self._require(
            self._processing_status()["processed_count"] == after_confirmation,
            "post-confirmation alias message reactivated semantic processing",
        )
        self.report.duplicate_identity = {
            "canonical_topic": canonical,
            "alias_topic": alias,
        }
        self._wait_persistence_clean(timeout=120)
        self.report.passed("duplicate canonical identity and KEEP_BOTH isolation")

    def _insert_pending_pair(self, topic_a: str, topic_b: str) -> None:
        first, second = sorted((topic_a, topic_b))
        sql = (
            "INSERT INTO duplicates(topic_a, topic_b, score, status) VALUES "
            f"('{first}', '{second}', 1.0, 'PENDING') "
            "ON CONFLICT (topic_a, topic_b) DO UPDATE SET status='PENDING'"
        )
        self._compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            self.environment.get("POSTGRES_USER", "influxai"),
            "-d",
            self.environment.get("POSTGRES_DB", "influxai"),
            "-c",
            sql,
        )

    # ---- recovery --------------------------------------------------------

    def _verify_restart_recovery(self) -> None:
        before = self._semantic_snapshots()
        persistence = self._wait_persistence_clean()
        generation = persistence["persisted_generation"]
        self._compose("stop", "-t", "30", "backend", timeout=45)
        self._compose("start", "backend")
        self._wait_ready()
        restored = self._json_request(
            "GET", f"{self.api}/semantic-review/persistence-status"
        )
        self._require(restored["restored"] is True, "restart did not restore state")
        self._require(
            restored["current_generation"] == generation,
            "restart restored a different semantic generation",
        )
        after = self._semantic_snapshots()
        self._require(after == before, "reviewed semantic state changed across restart")
        if self.report.duplicate_identity is not None:
            alias = self.report.duplicate_identity["alias_topic"]
            canonical = self.report.duplicate_identity["canonical_topic"]
            identity = self._json_request(
                "GET",
                f"{self.api}/duplicate-identity/{urllib.parse.quote(alias, safe='')}",
            )
            self._require(
                identity["canonical_topic"] == canonical
                and identity["state"] == "DUPLICATE_ALIAS",
                "canonical identity did not survive restart",
            )
        self.report.passed("backend restart and exact semantic recovery")

    def _verify_broker_recovery(self) -> None:
        self._compose("stop", "mqtt")
        self._wait(
            "broker dependency degradation",
            lambda: not self._dependency_healthy("MQTTClient"),
        )
        self._require(
            self._http_status(f"{self.api}/health/live") == 200,
            "backend liveness failed during broker outage",
        )
        failed_publish = self._compose_result(
            "exec",
            "-T",
            "mqtt",
            "mosquitto_pub",
            "-h",
            "localhost",
            "-t",
            f"{self.prefix}/broker-down",
            "-m",
            "{}",
            check=False,
        )
        self._require(failed_publish.returncode != 0, "publish unexpectedly succeeded")

        self._compose("start", "mqtt")
        self._wait("broker container recovery", lambda: self._container_healthy("mqtt"))
        consecutive_healthy = 0

        def subscriptions_restored() -> bool:
            nonlocal consecutive_healthy
            if self._dependency_healthy("MQTTClient"):
                consecutive_healthy += 1
            else:
                consecutive_healthy = 0
            # Dependency health is published before the asynchronous recovery
            # callback finishes restoring every persisted subscription.
            return consecutive_healthy >= 5

        self._wait(
            "stable backend broker recovery and subscription restoration",
            subscriptions_restored,
        )
        topic = f"{self.prefix}/broker-recovered"
        baseline = self._processing_status()["processed_count"]
        self._publish(topic, fields={"reading": 1.0}, tags={"site": "acceptance"})
        self._wait_influx(topic)
        self._wait_processing_total(baseline + 1, timeout=180)
        self.report.passed(
            "broker outage, reconnect, resubscribe, and resumed ingestion"
        )

    def _verify_postgres_recovery(self, group_b: tuple[str, ...]) -> None:
        candidates = self._json_request(
            "GET", f"{self.api}/semantic-review/candidates"
        )["candidates"]
        candidate_b = self._candidate_for(candidates, group_b)
        self._require(
            candidate_b is not None, "second pending candidate was not restored"
        )
        failure_before = self._json_request(
            "GET", f"{self.api}/semantic-review/persistence-status"
        )["failed_save_count"]

        self._compose("stop", "postgres")
        self._wait(
            "PostgreSQL dependency degradation",
            lambda: not self._dependency_healthy("PostgresClient"),
        )
        self._require(
            self._http_status(f"{self.api}/health/live") == 200,
            "backend liveness failed during PostgreSQL outage",
        )
        review = self._review_payload(
            candidate_b,
            class_id=f"acceptance-{self.run_id}-pressure",
            class_name=f"Acceptance {self.run_id} pressure",
            kept=group_b,
            removed=(),
        )
        result = self._json_request(
            "POST", f"{self.api}/semantic-review/reviews", review
        )
        self._require(result.get("registry_updated") is True, "in-memory review failed")

        self._wait(
            "persistence save failure status",
            lambda: self._persistence_failed_after(failure_before),
            timeout=60,
        )
        self._compose("start", "postgres")
        self._wait(
            "PostgreSQL container recovery",
            lambda: self._container_healthy("postgres"),
        )
        self._json_request("POST", f"{self.api}/semantic-review/persistence-retry", {})
        self._wait_persistence_clean(timeout=90)
        self._wait_ready()
        self.report.passed("PostgreSQL outage, degraded save, retry, and recovery")

    def _persistence_failed_after(self, count: int) -> bool:
        status = self._json_request(
            "GET", f"{self.api}/semantic-review/persistence-status"
        )
        return (
            status["failed_save_count"] > count
            and status["degraded"] is True
            and status["last_error_message"] is not None
        )

    # ---- backpressure and shutdown --------------------------------------

    def _verify_backpressure(self) -> None:
        before = self._processing_status()
        burst_size = 80
        topic = f"{self.prefix}/temperature/subsequent"
        payloads = [
            self._payload(
                fields={f"acceptance_burst_{index:03d}": float(index)},
                tags={"kind": "temperature", "site": "acceptance"},
                offset=index,
            )
            for index in range(burst_size)
        ]
        command = self._compose_prefix + [
            "exec",
            "-T",
            "mqtt",
            "mosquitto_pub",
            "-h",
            "localhost",
            "-q",
            "1",
            "-t",
            topic,
            "-l",
        ]
        self._run_command(command, input_text="\n".join(payloads) + "\n", timeout=60)

        final: dict[str, Any] = {}

        def accounted() -> bool:
            nonlocal final
            final = self._processing_status()
            submitted = final["submitted_count"] - before["submitted_count"]
            dropped = final["dropped_count"] - before["dropped_count"]
            completed = (
                final["processed_count"]
                - before["processed_count"]
                + final["failed_count"]
                - before["failed_count"]
            )
            return (
                submitted + dropped >= burst_size
                and final["queue_size"] == 0
                and completed == submitted
            )

        self._wait("bounded semantic queue accounting", accounted, timeout=300)
        submitted = final["submitted_count"] - before["submitted_count"]
        processed = final["processed_count"] - before["processed_count"]
        failed = final["failed_count"] - before["failed_count"]
        dropped = final["dropped_count"] - before["dropped_count"]
        self._require(
            dropped > 0, "acceptance burst did not exercise queue-full handling"
        )
        self._require(
            processed + failed == submitted, "accepted work accounting is inconsistent"
        )
        self.report.backpressure = {
            "published": burst_size,
            "submitted": submitted,
            "processed": processed,
            "failed": failed,
            "dropped": dropped,
        }
        self.report.passed("deterministic bounded-queue backpressure accounting")

    def _verify_bounded_shutdown_and_final_flush(self) -> None:
        clean = self._wait_persistence_clean(timeout=120)
        generation = clean["current_generation"]
        started = time.monotonic()
        self._compose("stop", "-t", "30", "backend", timeout=45)
        elapsed = time.monotonic() - started
        self._require(elapsed <= 45, "backend shutdown exceeded its external bound")

        state_key = self.environment["SEMANTIC_PERSISTENCE_STATE_KEY"]
        postgres_user = self.environment.get("POSTGRES_USER", "influxai")
        postgres_db = self.environment.get("POSTGRES_DB", "influxai")
        sql = (
            "SELECT generation FROM semantic_application_state "
            f"WHERE state_key = '{state_key}'"
        )
        stored = self._compose_output(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            postgres_user,
            "-d",
            postgres_db,
            "-tA",
            "-c",
            sql,
        ).strip()
        self._require(
            stored == str(generation), "final flush generation was not stored"
        )

        self._compose("start", "backend")
        self._wait_ready()
        restored = self._json_request(
            "GET", f"{self.api}/semantic-review/persistence-status"
        )
        self._require(restored["restored"] is True, "final restart did not restore")
        self._require(
            restored["current_generation"] == generation, "final generation changed"
        )
        self.report.final_generation = generation
        self.report.passed(f"bounded shutdown and final flush ({elapsed:.1f}s)")

    # ---- shared helpers --------------------------------------------------

    def _semantic_snapshots(self) -> dict[str, Any]:
        return {
            name: self._json_request("GET", f"{self.api}/semantic-review/{name}")
            for name in ("classes", "constraints", "candidates", "topic-states")
        }

    def _processing_status(self) -> dict[str, Any]:
        return self._json_request(
            "GET", f"{self.api}/semantic-review/processing-status"
        )

    def _wait_processing_total(
        self, expected: int, *, timeout: float | None = None
    ) -> None:
        self._wait(
            f"semantic processed_count >= {expected}",
            lambda: self._processing_status()["processed_count"] >= expected,
            timeout=timeout,
        )

    def _wait_persistence_clean(
        self, *, timeout: float | None = None
    ) -> dict[str, Any]:
        status: dict[str, Any] = {}

        def clean() -> bool:
            nonlocal status
            status = self._json_request(
                "GET", f"{self.api}/semantic-review/persistence-status"
            )
            return (
                status["save_pending"] is False
                and status["last_error_message"] is None
                and status["persisted_generation"] == status["current_generation"]
            )

        self._wait("semantic persistence clean", clean, timeout=timeout)
        return status

    def _dependency_healthy(self, name: str) -> bool:
        body = self._json_request("GET", f"{self.api}/health/details")
        return bool(body["dependencies"][name]["healthy"])

    def _wait_influx(self, topic: str) -> None:
        query = urllib.parse.urlencode({"names[]": topic})

        def present() -> bool:
            result = self._json_request("GET", f"{self.api}/timeseries?{query}")
            return bool(result and result[0].get("points"))

        self._wait(f"InfluxDB point for {topic}", present, timeout=120)

    def _publish(
        self, topic: str, *, fields: dict[str, Any], tags: dict[str, str]
    ) -> None:
        self._compose(
            "exec",
            "-T",
            "mqtt",
            "mosquitto_pub",
            "-h",
            "localhost",
            "-q",
            "1",
            "-t",
            topic,
            "-m",
            self._payload(fields=fields, tags=tags),
        )

    @staticmethod
    def _payload(
        *, fields: dict[str, Any], tags: dict[str, str], offset: int = 0
    ) -> str:
        timestamp = datetime.now(timezone.utc) + timedelta(microseconds=offset)
        return json.dumps(
            {
                "fields": fields,
                "tags": tags,
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def _json_request(
        self, method: str, url: str, body: dict[str, Any] | None = None
    ) -> Any:
        data = None
        headers: dict[str, str] = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise AcceptanceFailure(
                f"{method} {url} returned {exc.code}: {detail}"
            ) from exc

    @staticmethod
    def _http_status(url: str) -> int | None:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except (OSError, urllib.error.URLError):
            return None

    @staticmethod
    def _url_ok(url: str) -> bool:
        return RealStackAcceptance._http_status(url) == 200

    def _wait(
        self,
        description: str,
        predicate: Callable[[], bool],
        *,
        timeout: float | None = None,
        interval: float = 1.0,
    ) -> None:
        deadline = time.monotonic() + (timeout or self.timeout)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception as exc:  # noqa: BLE001 - transient polling boundary
                last_error = exc
            time.sleep(interval)
        suffix = f"; last error: {last_error}" if last_error else ""
        raise AcceptanceFailure(f"timed out waiting for {description}{suffix}")

    def _compose(self, *args: str, timeout: float | None = None) -> None:
        self._compose_result(*args, timeout=timeout)

    def _compose_output(self, *args: str) -> str:
        return self._compose_result(*args).stdout

    def _compose_result(
        self,
        *args: str,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_command(
            self._compose_prefix + list(args), timeout=timeout, check=check
        )

    def _run_command(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=self.environment,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout or self.timeout,
            check=False,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip()[-2000:]
            raise AcceptanceFailure(
                f"command failed ({result.returncode}): {' '.join(command[:8])}\n{stderr}"
            )
        return result

    @staticmethod
    def _require(condition: bool, message: str) -> None:
        if not condition:
            raise AcceptanceFailure(message)

    def _diagnostics(self) -> str:
        sections = []
        for label, args in (
            ("compose ps", ("ps", "-a")),
            ("backend logs", ("logs", "--no-color", "--tail", "120", "backend")),
        ):
            try:
                result = self._compose_result(*args, check=False, timeout=30)
                sections.append(
                    f"--- {label} ---\n{result.stdout[-12000:]}{result.stderr[-2000:]}"
                )
            except Exception as exc:  # noqa: BLE001 - preserve root failure
                sections.append(f"--- {label} unavailable: {exc} ---")
        return "\n".join(sections)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=validate_run_id, default=default_run_id())
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    runner = RealStackAcceptance(args.run_id, timeout=args.timeout)
    try:
        report = runner.run()
    except (AcceptanceFailure, subprocess.TimeoutExpired) as exc:
        print(f"FAIL real-stack acceptance\n{exc}", file=sys.stderr, flush=True)
        return 1
    print(json.dumps(report.__dict__, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
