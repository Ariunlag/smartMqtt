from services.influx.client import influx_client
from config import config
from models.api_models import TopicListResponse, MeasurementSeriesResponse, MeasurementPoint


class QueryManager:
    def __init__(self):
        self.client = influx_client

    async def list_measurements(self) -> TopicListResponse:
        """Return all measurement names in the bucket."""
        flux = f'''
        import "influxdata/influxdb/schema"
        schema.measurements(bucket: "{config.INFLUX_BUCKET}")
        '''
        try:
            result = self.client.query_raw(flux)
            names = []
            if result:
                for table in result:
                    for record in table.records:
                        names.append(record["_value"])
            return names
        except Exception as e:
            print(f"[QueryManager] Failed to list measurements: {e}")
            return TopicListResponse(topics=[])

    async def get_timeseries(self, measurements: list[str], start: str, stop: str = "now()") -> list[MeasurementSeriesResponse]:
        """Fetch time-series data for one or more measurements."""
        if not measurements:
            return []

        filter_str = " or ".join([f'r._measurement == "{m}"' for m in measurements])
        flux = f'''
        from(bucket: "{config.INFLUX_BUCKET}")
          |> range(start: {start}, stop: {stop})
          |> filter(fn: (r) => {filter_str})
        '''
        rows = await self._run(flux)

        results = []
        for name in measurements:
            filtered = [r for r in rows if r["measurement"] == name]
            points = [
                MeasurementPoint(timestamp=r["time"], value=r["value"])
                for r in filtered if isinstance(r["value"], (int, float))
            ]
            results.append(MeasurementSeriesResponse(measurement=name, points=points))
        return results
    
    async def get_recent_messages(self, limit: int = 200):
        """Return the most recent N messages across all measurements (topics)."""
        measurements = await self.list_measurements()
        if not measurements:
            return []
        filter_str = " or ".join([f'r._measurement == "{m}"' for m in measurements])
        row_limit = max(limit * 10, limit)
        flux = f'''
        from(bucket: "{config.INFLUX_BUCKET}")
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
        """
        Return the last N numeric points for a specific measurement (topic).
        Used for cosine/correlation similarity checks.
        """
        flux = f'''
        from(bucket: "{config.INFLUX_BUCKET}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._measurement == "{topic}")
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: {limit})
        '''
        rows = await self._run(flux)
        # Return only numeric values in consistent dict format
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
                        rows.append({
                            "time": record.get_time(),
                            "measurement": record.get_measurement(),
                            "field": record.get_field(),
                            "value": record.get_value(),
                            "tags": {
                                k: v for k, v in record.values.items()
                                if not k.startswith("_")
                                and k not in ["result", "table"]
                            }
                        })
            return rows
        except Exception as e:
            print(f"[QueryManager] Query failed: {e}")
            return []

# Singleton
query_manager = QueryManager()
