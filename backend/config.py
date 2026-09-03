import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # MQTT
        self.MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
        self.MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

        # InfluxDB
        self.INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
        self.INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "smartHub")
        self.INFLUX_ORG = os.getenv("INFLUX_ORG", "influxai")
        self.INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")

        # PostgreSQL metadata, relationships, and pgvector embeddings
        self.POSTGRES_DSN = os.getenv(
            "POSTGRES_DSN",
            "postgresql://influxai:influxai@localhost:5432/influxai",
        )
        self.POSTGRES_POOL_MAX_SIZE = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "10"))
        self.POSTGRES_POOL_TIMEOUT = float(os.getenv("POSTGRES_POOL_TIMEOUT", "5.0"))
        if self.POSTGRES_POOL_MAX_SIZE < 1:
            raise ValueError("POSTGRES_POOL_MAX_SIZE must be at least 1")
        if self.POSTGRES_POOL_TIMEOUT <= 0:
            raise ValueError("POSTGRES_POOL_TIMEOUT must be positive")

        # Runtime host/port and browser access.
        self.BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
        self.BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
        self.CORS_ALLOWED_ORIGINS = self._csv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost,http://127.0.0.1,http://localhost:5173,http://127.0.0.1:5173",
        )

        # Embedding model config. The pgvector schema currently fixes the vector
        # dimension at 384; changing model dimensionality requires a migration.
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
        self.EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))
        if self.EMBEDDING_DIMENSION != 384:
            raise ValueError(
                "EMBEDDING_DIMENSION must remain 384 until the pgvector schema is migrated"
            )

        # Duplicate detection
        self.ID_THRESH = self._ratio("ID_THRESH", 0.90)
        self.MIN_POINTS = int(os.getenv("MIN_POINTS", "10"))
        self.DUPE_CHECK_DELAY = int(os.getenv("DUPE_CHECK_DELAY", "60"))

        # Dependency health / recovery
        self.HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "2.0"))
        self.RECOVERY_BASE_DELAY = float(os.getenv("RECOVERY_BASE_DELAY", "2.0"))
        self.RECOVERY_MAX_DELAY = float(os.getenv("RECOVERY_MAX_DELAY", "30.0"))

        # MQTT ingestion queue / backpressure
        self.INGEST_QUEUE_MAXSIZE = int(os.getenv("INGEST_QUEUE_MAXSIZE", "1000"))
        self.INGEST_WORKERS = int(os.getenv("INGEST_WORKERS", "4"))
        self.INGEST_QUEUE_FULL_POLICY = os.getenv(
            "INGEST_QUEUE_FULL_POLICY", "drop_new"
        )
        self.INGEST_MAX_RETRIES = int(os.getenv("INGEST_MAX_RETRIES", "0"))
        self.INGEST_RETRY_DELAY = float(os.getenv("INGEST_RETRY_DELAY", "0.5"))
        self.INGEST_METRICS_INTERVAL = float(
            os.getenv("INGEST_METRICS_INTERVAL", "30.0")
        )

        # Topic-aware pair representation sidecar. The model remains lazy.
        self.CLASS_RECOMMENDATION_QUEUE_MAXSIZE = int(
            os.getenv("CLASS_RECOMMENDATION_QUEUE_MAXSIZE", "1000")
        )

        # Normal user-facing discovery excludes synthetic acceptance namespaces.
        # Acceptance Compose explicitly clears this value so the real-stack harness
        # can continue discovering its own fixture topics.
        self.SYSTEM_RECOMMENDATION_EXCLUDED_TOPIC_PREFIXES = self._csv(
            "SYSTEM_RECOMMENDATION_EXCLUDED_TOPIC_PREFIXES", "acceptance/"
        )

        # HDBSCAN recommendation baseline. These are clustering controls, not
        # semantic-similarity thresholds or cross-evidence weights.
        self.SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE = int(
            os.getenv("SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE", "2")
        )
        self.SYSTEM_RECOMMENDATION_MIN_SAMPLES = int(
            os.getenv("SYSTEM_RECOMMENDATION_MIN_SAMPLES", "1")
        )
        self.SYSTEM_RECOMMENDATION_ALLOW_SINGLE_CLUSTER = self._boolean(
            "SYSTEM_RECOMMENDATION_ALLOW_SINGLE_CLUSTER", False
        )
        if self.SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE < 2:
            raise ValueError("SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE must be at least 2")
        if self.SYSTEM_RECOMMENDATION_MIN_SAMPLES < 1:
            raise ValueError("SYSTEM_RECOMMENDATION_MIN_SAMPLES must be at least 1")

        # Original tag-value centroid baseline, now exposed as a recommendation
        # strategy over the same stored pair evidence.
        self.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_THRESHOLD = self._ratio(
            "SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_THRESHOLD", 0.85
        )
        self.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_MIN_TOPICS = int(
            os.getenv("SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_MIN_TOPICS", "2")
        )
        if self.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_MIN_TOPICS < 2:
            raise ValueError(
                "SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_MIN_TOPICS must be at least 2"
            )

    @staticmethod
    def _ratio(name: str, default: float) -> float:
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

    @staticmethod
    def _csv(name: str, default: str = "") -> tuple[str, ...]:
        value = os.getenv(name, default)
        return tuple(item.strip() for item in value.split(",") if item.strip())


config = Config()
