"""Run non-destructive real-stack acceptance for system recommendations + pgvector."""

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
    candidate_id: str | None = None
    duplicate_identity: dict[str, str] | None = None
    vector_counts: dict[str, int] | None = None

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
            topics = self._publish_recommendation_fixture()
            self._verify_system_candidate(topics)
            self._verify_strategy_selection(topics)
            self._verify_pgvector_material()
            self._verify_duplicate_keep_both()
            self._verify_confirmed_duplicate_identity()
            self._verify_restart_recovery()
            self.report.passed("complete system recommendation real-stack acceptance")
            return self.report
        except Exception as exc:
            raise AcceptanceFailure(f"{exc}\n\n{self._diagnostics()}") from exc

    def _start_stack(self) -> None:
        self._compose("build", "backend", "migrate", "frontend", timeout=900)
        self._compose("up", "-d", "postgres", "influxdb", "mqtt")
        for service in ("postgres", "influxdb", "mqtt"):
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
        self._require(
            self._sql_scalar(
                "SELECT count(*) FROM pg_extension WHERE extname = 'vector';"
            )
            == 1,
            "pgvector extension is not enabled",
        )
        self.report.passed("pgvector migration and full Compose startup")

    def _publish_recommendation_fixture(self) -> tuple[str, ...]:
        wildcard = f"{self.prefix}/#"
        self._json("POST", f"{self.api}/subscribe", {"topic": wildcard})
        topics = tuple(f"{self.prefix}/temperature/sensor-{index}" for index in range(4))
        baseline = self._processing_status()["processed"]
        for index, topic in enumerate(topics):
            self._publish(
                topic,
                fields={"temperature": 20.0 + index * 0.25},
                tags={"unit": "celsius", "site": "acceptance-lab"},
                offset=index,
            )
            self._wait_influx(topic)
        self._wait_processing(baseline + len(topics))
        self.report.passed("pair and stream evidence materialized for candidate fixture")
        return topics

    def _verify_system_candidate(self, expected_topics: tuple[str, ...]) -> None:
        candidate = None

        def found() -> bool:
            nonlocal candidate
            rows = self._json("GET", f"{self.api}/recommended-classes")["candidates"]
            expected = set(expected_topics)
            candidate = next(
                (
                    row
                    for row in rows
                    if len(expected.intersection(row["member_topics"])) >= 2
                ),
                None,
            )
            return candidate is not None

        self._wait("system recommended class candidate", found, timeout=300)
        self._require(candidate is not None, "candidate missing")
        encoded = json.dumps(candidate).lower()
        self._require("overall_score" not in encoded, "candidate exposed fused overall score")
        self._require(candidate["discovery_channels"], "independent discovery reasons missing")
        self._require(candidate["evidence"], "pair-level explanation evidence missing")
        first = candidate["evidence"][0]
        self._require("channel_scores" in first, "channel evidence missing")
        self._require("coverage" in first, "coverage evidence missing")
        self._require(first["matched_pairs"], "matched pair evidence missing")
        sources = {item["candidate"]["source"] for item in first["matched_pairs"]}
        self._require(sources.issubset({"tag", "field"}), "unexpected pair source")
        self.report.candidate_id = candidate["candidate_id"]
        self.report.passed("system candidate separated from Saved Classes with evidence")

    def _verify_strategy_selection(self, expected_topics: tuple[str, ...]) -> None:
        query = urllib.parse.urlencode({"strategy": "tag_value_centroid"})
        state = self._json("GET", f"{self.api}/recommended-classes?{query}")
        self._require(
            state["strategy"]["strategy_id"] == "tag_value_centroid",
            "tag-value centroid strategy was not selected",
        )
        strategy_ids = {item["strategy_id"] for item in state["strategy_catalog"]}
        self._require(
            {"independent_hdbscan", "tag_value_centroid"}.issubset(strategy_ids),
            "registered recommendation strategy catalog is incomplete",
        )
        expected = set(expected_topics)
        candidate = next(
            (
                row
                for row in state["candidates"]
                if len(expected.intersection(row["member_topics"])) >= 2
            ),
            None,
        )
        self._require(candidate is not None, "tag-value centroid produced no fixture candidate")
        self._require(
            candidate["discovery_channels"] == ["value"],
            "tag-value centroid did not report value-only discovery evidence",
        )
        self.report.passed("tag-value centroid strategy reuses shared pair evidence")

    def _verify_pgvector_material(self) -> None:
        prefix = self.prefix.replace("'", "''")
        topic_count = self._sql_scalar(
            "SELECT count(*) FROM topic_embeddings "
            f"WHERE payload->>'topic' LIKE '{prefix}/%';"
        )
        pair_count = self._sql_scalar(
            "SELECT count(*) FROM class_pair_embeddings "
            f"WHERE payload->>'canonical_topic' LIKE '{prefix}/%';"
        )
        self._require(topic_count >= 4, "topic embeddings were not persisted in pgvector")
        self._require(pair_count > 0, "pair embeddings were not persisted in pgvector")
        self._require(
            self._sql_scalar(
                "SELECT count(*) FROM pg_indexes "
                "WHERE indexname = 'idx_topic_embeddings_embedding_hnsw';"
            )
            == 1,
            "topic HNSW ANN index missing",
        )
        self.report.vector_counts = {"topic_embeddings": topic_count, "pair_embeddings": pair_count}
        self.report.passed("pgvector persistence and HNSW ANN index")

    def _verify_duplicate_keep_both(self) -> None:
        left = f"{self.prefix}/duplicate/keep-left"
        right = f"{self.prefix}/duplicate/keep-right"
        baseline = self._processing_status()["processed"]
        for topic in (left, right):
            self._publish(
                topic,
                fields={"temperature": 25.0},
                tags={"unit": "celsius", "site": "duplicate-keep"},
            )
        self._wait_processing(baseline + 2)
        pair = self._wait_duplicate_pair(left, right)
        self._json(
            "POST",
            f"{self.api}/duplicate-confirm",
            {"topics": pair["topics"], "action": "KEEP_BOTH"},
        )
        for topic in (left, right):
            identity = self._json(
                "GET",
                f"{self.api}/duplicate-identity/{urllib.parse.quote(topic, safe='')}",
            )
            self._require(identity["state"] == "ACTIVE_CANONICAL", "KEEP_BOTH changed identity")
        self.report.passed("pending duplicate KEEP_BOTH independence")

    def _verify_confirmed_duplicate_identity(self) -> None:
        canonical = f"{self.prefix}/duplicate/canonical"
        alias = f"{self.prefix}/duplicate/alias"
        baseline = self._processing_status()["processed"]
        for topic in (canonical, alias):
            self._publish(
                topic,
                fields={"temperature": 26.0},
                tags={"unit": "celsius", "site": "duplicate-confirm"},
            )
        self._wait_processing(baseline + 2)
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
        self._require(identity["state"] == "DUPLICATE_ALIAS", "alias state mismatch")
        candidate_state = self._json("GET", f"{self.api}/recommended-classes")
        self._require(
            all(alias not in row["member_topics"] for row in candidate_state["candidates"]),
            "confirmed alias remained an independent candidate member",
        )
        self.report.duplicate_identity = {"canonical": canonical, "alias": alias}
        self.report.passed("confirmed duplicate excluded from system candidates")

    def _verify_restart_recovery(self) -> None:
        before = dict(self.report.vector_counts or {})
        self._compose("restart", "backend", timeout=90)
        self._wait(
            "backend ready after restart",
            lambda: self._status(f"{self.api}/health/ready") == 200,
            timeout=300,
        )
        prefix = self.prefix.replace("'", "''")
        after = {
            "topic_embeddings": self._sql_scalar(
                "SELECT count(*) FROM topic_embeddings "
                f"WHERE payload->>'topic' LIKE '{prefix}/%';"
            ),
            "pair_embeddings": self._sql_scalar(
                "SELECT count(*) FROM class_pair_embeddings "
                f"WHERE payload->>'canonical_topic' LIKE '{prefix}/%';"
            ),
        }
        self._require(
            after["topic_embeddings"] >= before.get("topic_embeddings", 0),
            "topic vector evidence was lost across restart",
        )
        self._require(
            after["pair_embeddings"] >= before.get("pair_embeddings", 0),
            "pair vector evidence was lost across restart",
        )
        self._json("GET", f"{self.api}/recommended-classes")
        self.report.passed("restart recovery from PostgreSQL vector evidence")

    def _wait_duplicate_pair(self, left: str, right: str):
        found = None

        def present() -> bool:
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

    def _processing_status(self):
        return self._json("GET", f"{self.api}/class-recommendations/status")

    def _wait_processing(self, expected: int) -> None:
        self._wait(
            "recommendation processing",
            lambda: self._processing_status()["processed"] >= expected,
            timeout=300,
        )

    def _wait_influx(self, topic: str) -> None:
        query = urllib.parse.urlencode({"names[]": topic})
        self._wait(
            f"Influx point for {topic}",
            lambda: bool(self._json("GET", f"{self.api}/timeseries?{query}")),
            timeout=120,
        )

    def _publish(self, topic: str, *, fields: dict, tags: dict, offset: int = 0) -> None:
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
                "-m",
                self._payload(fields=fields, tags=tags, offset=offset),
            ],
            timeout=30,
        )

    @staticmethod
    def _payload(*, fields: dict, tags: dict, offset: int = 0) -> str:
        timestamp = datetime.now(UTC) + timedelta(milliseconds=offset)
        return json.dumps(
            {
                "fields": fields,
                "tags": tags,
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            },
            separators=(",", ":"),
        )

    def _container_healthy(self, service: str) -> bool:
        result = self._run(
            self._compose_prefix + ["ps", "-q", service],
            timeout=15,
            check=False,
        )
        container_id = result.stdout.strip()
        if not container_id:
            return False
        inspect = self._run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                container_id,
            ],
            timeout=15,
            check=False,
        )
        return inspect.stdout.strip() in {"healthy", "running"}

    def _sql_scalar(self, sql: str) -> int:
        result = self._run(
            self._compose_prefix
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                self.environment.get("POSTGRES_USER", "influxai"),
                "-d",
                self.environment.get("POSTGRES_DB", "influxai"),
                "-Atc",
                sql,
            ],
            timeout=30,
        )
        return int(result.stdout.strip() or "0")

    def _json(self, method: str, url: str, payload: dict | None = None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None

    @staticmethod
    def _status(url: str) -> int | None:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.status
        except Exception:
            return None

    def _wait(self, label: str, predicate, *, timeout: float | None = None) -> None:
        deadline = time.monotonic() + (timeout or self.timeout)
        last_error = None
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except Exception as exc:  # noqa: BLE001 - diagnostics retain last failure
                last_error = exc
            time.sleep(0.5)
        detail = f"; last error: {last_error}" if last_error else ""
        raise AcceptanceFailure(f"Timed out waiting for {label}{detail}")

    @staticmethod
    def _require(condition: bool, message: str) -> None:
        if not condition:
            raise AcceptanceFailure(message)

    def _compose(self, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
        return self._run(self._compose_prefix + list(args), timeout=timeout)

    def _run(
        self,
        command: list[str],
        *,
        timeout: float,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=check,
        )

    def _diagnostics(self) -> str:
        chunks = []
        for command in (
            self._compose_prefix + ["ps"],
            self._compose_prefix + ["logs", "--tail", "120", "backend"],
            self._compose_prefix + ["logs", "--tail", "80", "postgres"],
        ):
            result = self._run(command, timeout=30, check=False)
            chunks.append(
                f"$ {' '.join(command)}\n{result.stdout}\n{result.stderr}".strip()
            )
        return "\n\n".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=validate_run_id, default=default_run_id())
    args = parser.parse_args()
    report = RealStackAcceptance(args.run_id).run()
    print(json.dumps(report.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
