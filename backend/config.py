import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # MQTT
        self.MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
        self.MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))

        # InfluxDB
        self.INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
        self.INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "smartHub")
        self.INFLUX_ORG = os.getenv("INFLUX_ORG", "influxai")
        self.INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")

        # PostgreSQL metadata and relationships
        self.POSTGRES_DSN = os.getenv(
            "POSTGRES_DSN",
            "postgresql://influxai:influxai@localhost:5432/influxai",
        )

        # Qdrant semantic vectors
        self.QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

        # Runtime host/port
        self.BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
        self.BACKEND_PORT = int(os.getenv("BACKEND_PORT", 8000))

        # Embedding model config ( NEW)
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

        # Thresholds for duplicate detection
        self.ID_THRESH = self._ratio("ID_THRESH", 0.90)
        self.MIN_POINTS = int(os.getenv("MIN_POINTS", 10))

        # Duplicate check delay (in seconds)
        self.DUPE_CHECK_DELAY = int(
            os.getenv("DUPE_CHECK_DELAY", 60)
        )  # default 1 minute

        # threshold for group tags similarity (between 0 and 1)
        self.GROUP_TAG_THRESH = self._ratio("GROUP_TAG_THRESH", 0.85)

        # Dependency health / recovery
        self.HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", 2.0))
        self.RECOVERY_BASE_DELAY = float(os.getenv("RECOVERY_BASE_DELAY", 2.0))
        self.RECOVERY_MAX_DELAY = float(os.getenv("RECOVERY_MAX_DELAY", 30.0))

        # MQTT ingestion queue / backpressure
        self.INGEST_QUEUE_MAXSIZE = int(os.getenv("INGEST_QUEUE_MAXSIZE", 1000))
        self.INGEST_WORKERS = int(os.getenv("INGEST_WORKERS", 4))
        # "drop_new" (reject newest) or "drop_oldest" (evict oldest to admit new)
        self.INGEST_QUEUE_FULL_POLICY = os.getenv(
            "INGEST_QUEUE_FULL_POLICY", "drop_new"
        )
        self.INGEST_MAX_RETRIES = int(os.getenv("INGEST_MAX_RETRIES", 0))
        self.INGEST_RETRY_DELAY = float(os.getenv("INGEST_RETRY_DELAY", 0.5))
        self.INGEST_METRICS_INTERVAL = float(os.getenv("INGEST_METRICS_INTERVAL", 30.0))

        # Ordered semantic MQTT sidecar. Enabled by default; its model is still
        # constructed lazily during FastAPI startup rather than module import.
        self.SEMANTIC_PROCESSING_ENABLED = self._boolean(
            "SEMANTIC_PROCESSING_ENABLED", True
        )
        self.SEMANTIC_QUEUE_MAXSIZE = int(os.getenv("SEMANTIC_QUEUE_MAXSIZE", "256"))
        self.SEMANTIC_SHUTDOWN_DRAIN_TIMEOUT = float(
            os.getenv("SEMANTIC_SHUTDOWN_DRAIN_TIMEOUT", "5.0")
        )

    @staticmethod
    def _ratio(name: str, default: float) -> float:
        """Parse an env var as a similarity threshold in the inclusive [0, 1] range."""
        value = float(os.getenv(name, default))
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1, got {value}")
        return value

    @staticmethod
    def _boolean(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{name} must be a boolean, got {value!r}")


# single instance used everywhere
config = Config()
