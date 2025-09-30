from influxdb_client import InfluxDBClient, Point, WritePrecision
from config import config

class InfluxClient:
    def __init__(self, url: str, token: str, org: str):
        self.url = url
        self.token = token
        self.org = org
        self.client = None
        self.write_api = None
        self.query_api = None

    def connect(self):
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org
            )
            self.write_api = self.client.write_api()
            self.query_api = self.client.query_api()
            print(f"[InfluxClient] Connected to {self.url}")
        except Exception as e:
            print(f"[InfluxClient] Failed to connect: {e}")
            self.client = None

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
            print("[InfluxClient] Disconnected")

    def check_health(self) -> bool:
        """Return True if Influx server is healthy."""
        try:
            if not self.client:
                return False
            health = self.client.health()
            return getattr(health, "status", None) == "pass"
        except Exception:
            return False

    def write_point(self, measurement: str, tags: dict, fields: dict, timestamp=None):
        try:
            point = Point(measurement)
            for k, v in tags.items():
                point = point.tag(k, v)
            for k, v in fields.items():
                point = point.field(k, v)
            if timestamp:
                point = point.time(timestamp, WritePrecision.NS)
            self.write_api.write(bucket=config.INFLUX_BUCKET, record=point)
        except Exception as e:
            print(f"[InfluxClient] Failed to write point: {e}")

    def query_raw(self, flux: str):
        try:
            return self.query_api.query(flux)
        except Exception as e:
            print(f"[InfluxClient] Query failed: {e}")
            return None

# Singleton instance
influx_client = InfluxClient(
    url=config.INFLUX_URL,
    token=config.INFLUX_TOKEN,
    org=config.INFLUX_ORG
)
