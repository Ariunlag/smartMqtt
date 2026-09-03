import logging

from influxdb_client import InfluxDBClient, Point, WritePrecision

from config import config

logger = logging.getLogger(__name__)


class InfluxClient:
    def __init__(self, url: str, token: str, org: str):
        self.url = url
        self.token = token
        self.org = org
        self.client = None
        self.write_api = None
        self.query_api = None
        self.buckets_api = None

    def connect(self):
        if not self.token:
            # Keep dependency startup recoverable, but make the configuration defect
            # visible immediately instead of only through a later readiness failure.
            logger.warning(
                "[InfluxClient] INFLUX_TOKEN is empty; Influx readiness may fail"
            )
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org,
            )
            self.write_api = self.client.write_api()
            self.query_api = self.client.query_api()
            self.buckets_api = self.client.buckets_api()
            self._ensure_bucket()
            logger.info("[InfluxClient] Connected to %s", self.url)
        except Exception as exc:
            logger.warning("[InfluxClient] Failed to connect: %s", exc)
            self.client = None

    def _ensure_bucket(self):
        if not self.client or not self.buckets_api:
            return
        try:
            bucket = self.buckets_api.find_bucket_by_name(config.INFLUX_BUCKET)
            if bucket is None:
                org = self.client.organizations_api().find_organization_by_name(self.org)
                if org:
                    self.buckets_api.create_bucket(
                        bucket_name=config.INFLUX_BUCKET, org_id=org.id
                    )
                    logger.info(
                        "[InfluxClient] Created bucket %s", config.INFLUX_BUCKET
                    )
        except Exception as exc:
            logger.warning("[InfluxClient] Bucket setup failed: %s", exc)

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
            logger.info("[InfluxClient] Disconnected")

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
        if not self.write_api:
            raise RuntimeError("InfluxDB write API is not connected")
        point = Point(measurement)
        for key, value in tags.items():
            point = point.tag(key, value)
        for key, value in fields.items():
            point = point.field(key, value)
        if timestamp:
            point = point.time(timestamp, WritePrecision.NS)
        self.write_api.write(bucket=config.INFLUX_BUCKET, record=point)

    def query_raw(self, flux: str):
        try:
            return self.query_api.query(flux)
        except Exception as exc:
            logger.warning("[InfluxClient] Query failed: %s", exc)
            return None


# Singleton instance
influx_client = InfluxClient(
    url=config.INFLUX_URL,
    token=config.INFLUX_TOKEN,
    org=config.INFLUX_ORG,
)
