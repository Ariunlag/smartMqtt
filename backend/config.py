import os
from dotenv import load_dotenv

load_dotenv()  

class Config:
    def __init__(self):
        # MQTT
        self.MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
        self.MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))


        # InfluxDB
        self.INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
        self.INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "smartHub")
        self.INFLUX_ORG = os.getenv("INFLUX_ORG", "Test1")
        self.INFLUX_TOKEN = os.getenv("INFLUX_TOKEN",)

        # Embedding model config ( NEW)
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

       # Thresholds for duplicate detection
        self.ID_THRESH = float(os.getenv("ID_THRESH", 0.90))      
        self.MIN_POINTS = int(os.getenv("MIN_POINTS", 10))


        # Duplicate check delay (in seconds)
        self.DUPE_CHECK_DELAY = int(os.getenv("DUPE_CHECK_DELAY", 60))  # default 1 minute

        # threshold for group tags similarity (between 0 and 1)
        self.GROUP_TAG_THRESH = float(os.getenv("GROUP_TAG_THRESH", 0.85))


        # Data directory (for JSON stores)
        backend_dir = os.path.dirname(os.path.abspath(__file__))  # e.g. /project/backend
        self.DATA_DIR = os.getenv("DATA_DIR", os.path.join(backend_dir, "data"))

        os.makedirs(self.DATA_DIR, exist_ok=True)

# single instance used everywhere
config = Config()
