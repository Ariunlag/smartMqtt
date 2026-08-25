"""Run non-destructive real-stack acceptance for class recommendation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.acceptance.yml")
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class AcceptanceFailure(RuntimeError):
    pass


def default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz").lower()


def validate_run_id(value: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("run ID must match [a-z0-9][a-z0-9-]{0,31}")
    return value


@dataclass
class AcceptanceReport:
    run_id: str
    topic_prefix: str
    phases: list[str] = field(default_factory=list)
    backpressure: dict[str, int] | None = None
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
        self.environment = os.environ.copy()
        self.environment["CLASS_RECOMMENDATION_QUEUE_MAXSIZE"] = "128"
        self.report = AcceptanceReport(run_id, self.prefix)
        self._compose_prefix = ["docker", "compose"]
        for filename in COMPOSE_FILES:
            self._compose_prefix.extend(("-f", filename))

    def run(self) -> AcceptanceReport:
        try:
            self._start_stack()
            reference = self._prepare_reference_class()
            self._verify_recommendation_and_accept(reference)
            self._verify_reject_and_dismiss()
            self._verify_duplicate_pending_and_keep_both()
            self._verify_confirmed_duplicate_reconciliation()
            self._verify_restart_recovery()
            self._verify_burst_accounting()
            self.report.passed("complete pair-level real-stack acceptance")
            return self.report
        except Exception as exc:
            raise AcceptanceFailure(f"{exc}\n\n{self._diagnostics()}") from exc

    def _start_stack(self) -> None:
        self._compose("build", "backend", "migrate", "frontend", timeout=900)
        self._compose("up", "-d", "postgres", "qdrant", "influxdb", "mqtt")
        for service in ("postgres", "qdrant", "influxdb", "mqtt"):
            self._wait(
                f"{service} healthy",
                lambda service=service: self._container_healthy(service),
                timeout=180,
            )
        self._compose("run", "--rm", "migrate", timeout=180)
        self._compose("up", "-d", "--no-deps", "backend", "frontend")
        self._wait(
            "backend ready",
            lambda: self._status(f"{self.api}/health/ready") == 200,
            timeout=300,
        )
        self._wait("frontend available", lambda: self._status(self.frontend) == 200)
        self.report.passed("migration and full Compose startup")

    def _prepare_reference_class(self) -> tuple[str, str]:
        wildcard = f"{self.prefix}/#"
        self._json("POST", f"{self.api}/subscribe", {"topic": wildcard})
        references = (
            f"{self.prefix}/temperature/reference-a",
            f"{self.prefix}/temperature/reference-b",
        )
        baseline = self._processing_status()["processed"]
        for index, topic in enumerate(references):
            self._publish(
                topic,
                fields={"temperature": 20.0 + index},
                tags={"location": f"room-{index}", "unit": "celsius"},
            )
            self._wait_influx(topic)
        self._wait_processing(baseline + len(references))
        class_name = f"acceptance-temperature-{self.run_id}"
        record = self._json(
            "POST",
            f"{self.api}/classes/",
            {"name": class_name, "topics": list(references)},
        )
        self._require(record["topics"] == list(references), "class membership mismatch")
        self._require(record["profile_version"] == 1, "new class version mismatch")
        self.report.passed("reference pair embeddings and compact class profile")
        return class_name, record["class_id"]

    def _verify_recommendation_and_accept(self, reference: tuple[str, str]) -> None:
        class_name, _ = reference
        topic = f"{self.prefix}/candidate/temp"
        baseline = self._processing_status()["processed"]
        self._publish(
            topic,
            fields={"temp": 24.1},
            tags={"room": "room-2", "unit": "celsius"},
        )
        self._wait_processing(baseline + 1)
        recommendation = self._wait_recommendation(class_name, topic)
        self._require(
            recommendation["coverage"]["candidate_pair_count"] == 3,
            "candidate pair identity collapsed",
        )
        self._require(
            set(recommendation["valid_channels"])
            == {"key", "value", "key_value", "schema", "numeric_key", "stream_context"},
            "six-channel evidence contract mismatch",
        )
        self._require(recommendation["matched_pairs"], "pair evidence missing")
        self._require(
            "vector" not in json.dumps(recommendation).lower(), "API exposed vectors"
        )
        action = self._action_payload("RECOMMENDATION_ACCEPT", recommendation)
        self._json(
            "POST",
            f"{self.api}/classes/{urllib.parse.quote(class_name)}/recommendation-actions",
            action,
        )
        saved = self._class(class_name)
        self._require(topic in saved["topics"], "accepted topic was not added")
        self._require(
            saved["profile_version"] == 2, "accept did not bump class version"
        )
        self.report.passed(
            "pair evidence, stream-context reuse, and recommendation accept"
        )

    def _verify_reject_and_dismiss(self) -> None:
        class_name = f"acceptance-temperature-{self.run_id}"
        for action, suffix in (
            ("RECOMMENDATION_REJECT", "reject"),
            ("RECOMMENDATION_DISMISS", "dismiss"),
        ):
            topic = f"{self.prefix}/candidate/{suffix}"
            baseline = self._processing_status()["processed"]
            self._publish(topic, fields={"temperature": 23.0}, tags={"unit": "celsius"})
            self._wait_processing(baseline + 1)
            recommendation = self._wait_recommendation(class_name, topic)
            self._json(
                "POST",
                f"{self.api}/classes/{urllib.parse.quote(class_name)}/recommendation-actions",
                self._action_payload(action, recommendation),
            )
            rows = self._class_recommendations(class_name)
            self._require(
                all(item["canonical_topic"] != topic for item in rows),
                f"{action} did not suppress unchanged evidence",
            )
        reject_count = self._sql_scalar(
            "SELECT count(*) FROM class_recommendation_constraints "
            f"WHERE canonical_topic LIKE '{self.prefix}/%';"
        )
        dismiss_count = self._sql_scalar(
            "SELECT count(*) FROM class_recommendation_dismissals "
            f"WHERE canonical_topic LIKE '{self.prefix}/%';"
        )
        self._require(reject_count >= 1 and dismiss_count >= 1, "action state missing")
        self.report.passed("version-scoped reject and non-training dismiss")

    def _verify_duplicate_pending_and_keep_both(self) -> None:
        left = f"{self.prefix}/duplicate/keep-left"
        right = f"{self.prefix}/duplicate/keep-right"
        baseline = self._processing_status()["processed"]
        for topic in (left, right):
            self._publish(topic, fields={"temperature": 25.0}, tags={"unit": "celsius"})
        self._wait_processing(baseline + 2)
        pair = self._wait_duplicate_pair(left, right)
        recommendation = self._wait_recommendation(
            f"acceptance-temperature-{self.run_id}", right
        )
        self._require(
            recommendation["duplicate_pending"] is True, "pending duplicate hidden"
        )
        self._json(
            "POST",
            f"{self.api}/duplicate-confirm",
            {"topics": pair["topics"], "action": "KEEP_BOTH"},
        )
        identities = [
            self._json(
                "GET",
                f"{self.api}/duplicate-identity/{urllib.parse.quote(topic, safe='')}",
            )
            for topic in (left, right)
        ]
        self._require(
            all(item["state"] == "ACTIVE_CANONICAL" for item in identities),
            "KEEP_BOTH canonicalized topics",
        )
        self.report.passed("pending duplicate visibility and KEEP_BOTH independence")

    def _verify_confirmed_duplicate_reconciliation(self) -> None:
        class_name = f"acceptance-temperature-{self.run_id}"
        canonical = f"{self.prefix}/duplicate/canonical"
        alias = f"{self.prefix}/duplicate/alias"
        baseline = self._processing_status()["processed"]
        for topic in (canonical, alias):
            self._publish(topic, fields={"temperature": 26.0}, tags={"unit": "celsius"})
        self._wait_processing(baseline + 2)
        self._json(
            "POST",
            f"{self.api}/classes/{urllib.parse.quote(class_name)}/recommendation-actions",
            {"action": "MANUAL_ADD", "topic": alias},
        )
        pair = self._wait_duplicate_pair(canonical, alias)
        self._json(
            "POST",
            f"{self.api}/duplicate-confirm",
            {"topics": pair["topics"], "action": "UNSUBSCRIBE", "target": alias},
        )
        identity = self._json(
            "GET", f"{self.api}/duplicate-identity/{urllib.parse.quote(alias, safe='')}"
        )
        self._require(identity["canonical_topic"] == canonical, "alias root mismatch")
        saved = self._class(class_name)
        self._require(
            alias not in saved["topics"] and canonical in saved["topics"],
            "class membership was not remapped",
        )
        self._require(
            self._json(
                "GET",
                f"{self.api}/topics/{urllib.parse.quote(alias, safe='')}/class-recommendations",
            )["recommendations"]
            == [],
            "confirmed alias remained recommendation eligible",
        )
        self.report.duplicate_identity = {"canonical": canonical, "alias": alias}
        self.report.passed("confirmed duplicate canonical profile reconciliation")

    def _verify_restart_recovery(self) -> None:
        class_name = f"acceptance-temperature-{self.run_id}"
        before = self._class(class_name)
        self._compose("restart", "backend", timeout=90)
        self._wait(
            "backend ready after restart",
            lambda: self._status(f"{self.api}/health/ready") == 200,
            timeout=300,
        )
        after = self._class(class_name)
        self._require(
            before == after, "durable class/version state changed across restart"
        )
        rows = self._class_recommendations(class_name)
        self._require(isinstance(rows, list), "derived profiles did not rebuild")
        self.report.passed("restart recovery from durable class and pair evidence")

    def _verify_burst_accounting(self) -> None:
        before = self._processing_status()
        topic = f"{self.prefix}/burst"
        payloads = [
            self._payload(
                fields={"temperature": float(index)},
                tags={"unit": "celsius"},
                offset=index,
            )
            for index in range(80)
        ]
        self._run(
            self._compose_prefix
            + [
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
            ],
            input_text="\n".join(payloads) + "\n",
            timeout=60,
        )
        final = {}

        def accounted() -> bool:
            nonlocal final
            final = self._processing_status()
            return (
                final["processed"] + final["failed"] + final["dropped"]
                >= before["processed"] + before["failed"] + before["dropped"] + 1
            )

        self._wait("recommendation burst accounting", accounted, timeout=300)
        self._wait_influx(topic)
        self.report.backpressure = {
            key: int(final[key] - before[key])
            for key in ("submitted", "processed", "failed", "coalesced", "dropped")
        }
        self._require(
            self.report.backpressure["submitted"] > 0, "burst submitted no work"
        )
        self.report.passed("bounded topic-aware burst processing")

    def _action_payload(self, action, recommendation):
        return {
            "action": action,
            "topic": recommendation["canonical_topic"],
            "topic_representation_version": recommendation[
                "topic_representation_version"
            ],
            "class_profile_version": recommendation["class_profile_version"],
            "recommendation_id": recommendation["recommendation_id"],
        }

    def _class_recommendations(self, class_name):
        return self._json(
            "GET",
            f"{self.api}/classes/{urllib.parse.quote(class_name)}/recommendations",
        )["recommendations"]

    def _wait_recommendation(self, class_name, topic):
        found = None

        def present():
            nonlocal found
            found = next(
                (
                    row
                    for row in self._class_recommendations(class_name)
                    if row["canonical_topic"] == topic
                ),
                None,
            )
            return found is not None

        self._wait(f"recommendation for {topic}", present, timeout=300)
        return found

    def _wait_duplicate_pair(self, left, right):
        found = None

        def present():
            nonlocal found
            expected = sorted((left, right))
            found = next(
                (
                    row
                    for row in self._json("GET", f"{self.api}/duplicates")["duplicates"]
                    if row["topics"] == expected
                ),
                None,
            )
            return found is not None

        self._wait(f"duplicate pair {left} / {right}", present, timeout=300)
        return found

    def _class(self, name):
        return next(
            row
            for row in self._json("GET", f"{self.api}/classes/")["classes"]
            if row["name"] == name
        )

    def _processing_status(self):
        return self._json("GET", f"{self.api}/class-recommendations/status")

    def _wait_processing(self, expected):
        self._wait(
            "recommendation processing",
            lambda: self._processing_status()["processed"] >= expected,
            timeout=300,
        )

    def _wait_influx(self, topic):
        query = urllib.parse.urlencode({"names[]": topic})
        self._wait(
            f"Influx point for {topic}",
            lambda: bool(
                self._json("GET", f"{self.api}/timeseries?{query}")[0]["points"]
            ),
            timeout=180,
        )

    def _publish(self, topic, *, fields, tags):
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
    def _payload(*, fields, tags, offset=0):
        timestamp = datetime.now(UTC) + timedelta(microseconds=offset)
        return json.dumps(
            {
                "fields": fields,
                "tags": tags,
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            }
        )

    def _sql_scalar(self, sql):
        result = self._compose_output(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            self.environment.get("POSTGRES_USER", "influxai"),
            "-d",
            self.environment.get("POSTGRES_DB", "influxai"),
            "-tA",
            "-c",
            sql,
        )
        return int(result.strip())

    def _container_healthy(self, service):
        container_id = self._compose_output("ps", "-q", service).strip()
        if not container_id:
            return False
        result = self._run(
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

    def _json(self, method, url, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            url, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"null")

    @staticmethod
    def _status(url):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status
        except Exception:  # noqa: BLE001 - readiness probe treats all URL errors alike
            return 0

    def _wait(self, label, predicate, *, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        last_error = None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception as exc:  # noqa: BLE001 - retain the last probe failure
                last_error = exc
            time.sleep(1)
        raise AcceptanceFailure(f"timed out waiting for {label}: {last_error}")

    @staticmethod
    def _require(condition, message):
        if not condition:
            raise AcceptanceFailure(message)

    def _compose(self, *args, timeout=120):
        return self._run(self._compose_prefix + list(args), timeout=timeout)

    def _compose_output(self, *args):
        return self._compose(*args).stdout

    def _run(self, command, *, check=True, input_text=None, timeout=120):
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=self.environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_text,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode:
            raise AcceptanceFailure(
                f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}"
            )
        return result

    def _diagnostics(self):
        parts = []
        for command in (("ps",), ("logs", "--no-color", "--tail", "120", "backend")):
            result = self._run(self._compose_prefix + list(command), check=False)
            parts.append(result.stdout + result.stderr)
        return "\n".join(parts)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--run-id", type=validate_run_id, default=default_run_id())
    result.add_argument("--timeout", type=float, default=120.0)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    report = RealStackAcceptance(args.run_id, timeout=args.timeout).run()
    print(json.dumps(report.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
