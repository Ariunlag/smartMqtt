"""Windowed Pearson shape model: synchronized UTC bins, no amplitude/unit claim.

Reads persisted Influx points, so the coalescing recommendation queue cannot turn
high-frequency telemetry into a misleading time-series sample.
"""

import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import linear_sum_assignment

from .adaptive_evidence import ProviderDefinition, fingerprint


@dataclass(frozen=True)
class SeriesConfig:
    step_seconds: int = 60
    bins: int = 32
    min_points: int = 16
    max_fields: int = 16

    def __post_init__(self):
        if self.step_seconds < 1 or self.bins < 4 or not 3 <= self.min_points <= self.bins or self.max_fields < 1:
            raise ValueError("Invalid time-series window configuration")


class SeriesShapeProvider:
    def __init__(self, config=None, *, active=False, clock=time.time):
        self.config = config or SeriesConfig()
        self.clock = clock
        self.definition = ProviderDefinition(
            "series_shape", "Time-series shape", "series_window",
            version="pearson-utc-v1:" + fingerprint(asdict(self.config)),
            kind="numeric_features", active=active, comparator="masked-pearson-assignment",
            refresh_policy="closed-utc-window")

    def current_end(self):
        return int(self.clock() // self.config.step_seconds) * self.config.step_seconds

    def materialize(self, topic, tags, encode):
        return []  # Numeric materialization is driven by refresh_windows().

    def retrieval_records(self, rows):
        current = self.current_end()
        return [r for r in rows if r["payload"]["status"] == "available"
                and 0 <= current - r["payload"]["window_end"] <= self.config.step_seconds]

    def window_records(self, topic, tags, points, end):
        cfg = self.config
        start = end - cfg.bins * cfg.step_seconds
        fields = {}
        expected = {str(k): str(v) for k, v in tags.items()}
        for point in points:
            value = point["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            if {str(k): str(v) for k, v in point.get("tags", {}).items()} != expected:
                continue  # Never join different tag-set identities into one signal.
            timestamp = point["time"]
            timestamp = timestamp.timestamp() if isinstance(timestamp, datetime) else float(timestamp)
            slot = int((timestamp - start) // cfg.step_seconds)
            if not 0 <= slot < cfg.bins:
                continue
            field = point["field"]
            if field not in fields and len(fields) >= cfg.max_fields:
                continue
            fields.setdefault(field, {}).setdefault(slot, []).append(float(value))
        result = []
        for field, slots in sorted(fields.items()):
            values = [float(np.mean(slots[i])) if i in slots else None for i in range(cfg.bins)]
            observed = np.asarray([v for v in values if v is not None])
            status = "available" if len(observed) >= cfg.min_points else "warming"
            if len(observed) and np.std(observed) <= 1e-12 * max(1., float(np.max(np.abs(observed)))):
                status = "constant"
            # Mean-filled normalized sketch is retrieval-only. Comparison below
            # uses actual common observations, with no forward/backward filling.
            vector = None
            if status == "available":
                sketch = np.asarray([v if v is not None else float(observed.mean()) for v in values])
                sketch -= sketch.mean()
                vector = (sketch / np.linalg.norm(sketch)).tolist()
            result.append({"entity": fingerprint({"tags": tags, "field": field}), "embedding": vector,
                           "payload": {"field": field, "tags": tags, "values": values, "status": status,
                                       "window_end": end, "step_seconds": cfg.step_seconds,
                                       "text": f"{field} · {len(observed)}/{cfg.bins} UTC bins"}})
        return result

    def compare(self, left, right):
        missing = lambda status: {"score": None, "status": status, "coverage": 0., "matches": []}
        if not left or not right:
            return missing("warming")
        current = self.current_end()
        a, b = self.retrieval_records(left), self.retrieval_records(right)
        if not a or not b:
            stale = any(current - r["payload"]["window_end"] > self.config.step_seconds for r in [*left, *right])
            return missing("stale" if stale else "warming")
        matrix = np.full((len(a), len(b)), -1.)
        coverage = np.zeros_like(matrix)
        for i, x in enumerate(a):
            for j, y in enumerate(b):
                xp, yp = x["payload"], y["payload"]
                if xp["window_end"] != yp["window_end"] or xp["step_seconds"] != yp["step_seconds"]:
                    continue
                xv, yv = np.asarray(xp["values"], float), np.asarray(yp["values"], float)
                common = np.isfinite(xv) & np.isfinite(yv)
                if common.sum() < self.config.min_points:
                    continue
                xx, yy = xv[common] - xv[common].mean(), yv[common] - yv[common].mean()
                norm = np.linalg.norm(xx) * np.linalg.norm(yy)
                if norm <= 1e-12:
                    continue
                matrix[i, j] = (float(np.clip(xx @ yy / norm, -1, 1)) + 1) / 2
                coverage[i, j] = float(common.sum() / self.config.bins)
        rows, cols = linear_sum_assignment(matrix * coverage + (matrix < 0) * -1, maximize=True)
        matches = [(i, j) for i, j in zip(rows, cols, strict=True) if matrix[i, j] >= 0]
        if not matches:
            return missing("warming")
        total_coverage = sum(coverage[i, j] for i, j in matches)
        return {"status": "available", "score": float(sum(matrix[i, j] * coverage[i, j] for i, j in matches) / total_coverage),
                "coverage": float(total_coverage / max(len(left), len(right))),
                "matches": [{"left": a[i]["payload"], "right": b[j]["payload"],
                             "similarity": float(matrix[i, j])} for i, j in matches]}


class InfluxSeriesSource:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def fetch(self, topics, end, config):
        from services.query_manager import _flux_string_literal
        quote = _flux_string_literal
        if not topics:
            return {}
        if not self.client.query_api:
            raise RuntimeError("InfluxDB query API is not connected")
        start = end - config.step_seconds * config.bins
        timestamp = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
        result = {topic: [] for topic in topics}
        for offset in range(0, len(topics), 32):
            batch = topics[offset:offset + 32]
            predicate = " or ".join(f"r._measurement == {quote(t)}" for t in batch)
            flux = f'''import "types"
from(bucket: {quote(self.bucket)})
  |> range(start: time(v: {quote(timestamp(start))}), stop: time(v: {quote(timestamp(end))}))
  |> filter(fn: (r) => {predicate})
  |> filter(fn: (r) => types.isNumeric(v: r._value))
  |> toFloat()
  |> aggregateWindow(every: {config.step_seconds}s, fn: mean, createEmpty: false, timeSrc: "_start")
  |> limit(n: {config.bins})'''
            for record in self.client.query_api.query_stream(flux):
                topic = record.get_measurement()
                # Bound material memory even if a topic has many historic tag sets.
                if topic not in result or len(result[topic]) >= config.bins * config.max_fields * 4:
                    continue
                result[topic].append({"field": record.get_field(), "time": record.get_time(),
                                      "value": record.get_value(), "tags": {k: v for k, v in record.values.items()
                                      if not k.startswith("_") and k not in {"result", "table"}}})
        return result
