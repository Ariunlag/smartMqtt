import json
import logging

from config import config
from models.api_models import MeasurementPoint, MeasurementSeriesResponse, TopicListResponse
from services.influx.client import influx_client

logger = logging.getLogger(__name__)


def _flux_string_literal(value: object) -> str:
    """Render an untrusted value as one Flux string literal.

    Flux uses JSON-style escapes for quoted strings. Encoding the complete value rather
    than interpolating inside hand-written quotes prevents measurements/topics from
    terminating the literal and injecting Flux syntax.
    """
    return json.dumps(str(value), ensure_ascii=False)


def _measurement_filter(measurements: list[str]) -> str:
    return " or ".join(
        f"r._measurement == {_flux_string_literal(measurement)}"
        for measurement in measurements
    )


class QueryManager:
    def __init__(self):
        self.client = influx_client

    async def list_measurements(self) -> TopicListResponse:
        """Return all measurement names in the bucket."""
        bucket = _flux_string_literal(config.INFLUX_BUCKET)
        flux = f'''
        import "influxdata/influxdb/schema"
        schema.measurements(bucket: {bucket})
        '''
        try:
            result = self.client.query_raw(flux)
            names = []
            if result:
                for table in result:
                    for record in table.records:
                        names.append(record["_value"])
            return names
        except Exception as exc:
            logger.warning("[QueryManager] Failed to list measurements: %s", exc)
            return TopicListResponse(topics=[])

    async def get_timeseries(
        self, measurements: list[str], start: str, stop: str = "now()"
    ) -> list[MeasurementSeriesResponse]:
        """Fetch time-series data for one or more measurements."""
        if not measurements:
            return []

        filter_str = _measurement_filter(measurements)
        bucket = _flux_string_literal(config.INFLUX_BUCKET)
        flux = f'''
        from(bucket: {bucket})
          |> range(start: {start}, stop: {stop})
          |> filter(fn: (r) => {filter_str})
        '''
        rows = await self._run(flux)

        results = []
        for name in measurements:
            filtered = [r for r in rows if r["measurement"] == name]
            points = [
                MeasurementPoint(timestamp=r["time"], value=r["value"])
                for r in filtered
                if isinstance(r["value"], (int, float))
            ]
            results.append(MeasurementSeriesResponse(measurement=name, points=points))
        return results

    async def get_recent_messages(self, limit: int = 200):
        """Return the most recent N messages across all measurements (topics)."""
        measurements = await self.list_measurements()
        if not measurements:
            return []
        filter_str = _measurement_filter(measurements)
        bucket = _flux_string_literal(config.INFLUX_BUCKET)
        row_limit = max(limit * 10, limit)
        flux = f'''
        from(bucket: {bucket})
        |> range(start: -1h)
        |> filter(fn: (r) => {filter_str})
        |> sort(columns: ["_time"], desc: true)
        |> limit(n: {row_limit})
        '''
        rows = await self._run(flux)
        messages = {}
        for row in rows:
            key = (row["measurement"], row["time"])
            if key not in messages:
                messages[key] = {
                    "topic": row["measurement"],
                    "timestamp": row["time"],
                    "tags": row["tags"],
                    "fields": {},
                }
            messages[key]["fields"][row["field"]] = row["value"]
        return list(messages.values())[:limit]

    async def get_last_points(self, topic: str, limit: int = 100):
        """Return the last N numeric points for a specific measurement (topic)."""
        bucket = _flux_string_literal(config.INFLUX_BUCKET)
        topic_literal = _flux_string_literal(topic)
        flux = f'''
        from(bucket: {bucket})
          |> range(start: -24h)
          |> filter(fn: (r) => r._measurement == {topic_literal})
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: {limit})
        '''
        rows = await self._run(flux)
        return [
            {"time": r["time"], "value": r["value"]}
            for r in rows
            if isinstance(r["value"], (int, float))
        ]

    async def _run(self, flux: str):
        """Internal helper to execute Flux queries and return structured results."""
        try:
            result = self.client.query_raw(flux)
            rows = []
            if result:
                for table in result:
                    for record in table.records:
                        rows.append(
                            {
                                "time": record.get_time(),
                                "measurement": record.get_measurement(),
                                "field": record.get_field(),
                                "value": record.get_value(),
                                "tags": {
                                    k: v
                                    for k, v in record.values.items()
                                    if not k.startswith("_")
                                    and k not in ["result", "table"]
                                },
                            }
                        )
            return rows
        except Exception as exc:
            logger.warning("[QueryManager] Query failed: %s", exc)
            return []


query_manager = QueryManager()
