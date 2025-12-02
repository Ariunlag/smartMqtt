# test/dupe_publisher.py
import json
import time
import random
import math
import paho.mqtt.client as mqtt


TOPICS = [
    # ---------- DUPLICATE GROUP 1: Temperature sensors ----------
    ("building/nyc/temperature", {
        "location": "New York City",
        "zone": "office_floor_1",
        "sensor_type": "temperature",
        "unit": "celsius"
    }),
    ("sensors/manhattan/temp_sensor", {
        "location": "Manhattan",
        "zone": "office_floor_1",
        "sensor_type": "temp",
        "unit": "°C"
    }),

    # ---------- DUPLICATE GROUP 2: CO2 sensors ----------
    ("air_quality/lab/co2_level", {
        "location": "Boston Lab",
        "zone": "lab_A",
        "sensor_type": "co2",
        "unit": "ppm"
    }),
    ("environment/boston/carbon_dioxide", {
        "location": "Boston City Center",
        "zone": "lab_A",
        "sensor_type": "carbon_dioxide",
        "unit": "parts_per_million"
    }),

    # ---------- NON-DUPES but with similar tags ----------
    ("building/nyc/humidity", {
        "location": "New York City",
        "zone": "office_floor_2",
        "sensor_type": "humidity",
        "unit": "%"
    }),
    ("building/boston/humidity", {
        "location": "Boston",
        "zone": "office_floor_3",
        "sensor_type": "humidity",
        "unit": "%"
    }),
    ("weather/los_angeles/temperature", {
        "location": "Los Angeles",
        "zone": "outdoor_station",
        "sensor_type": "temperature",
        "unit": "fahrenheit"
    }),
]


# ============================================================
# 🚀 MQTT Publisher Class
# ============================================================
class MQTTPublisher:
    def __init__(self, broker: str, port: int):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.broker = broker
        self.port = port

    def connect(self):
        """Connect to MQTT broker."""
        self.client.connect(self.broker, self.port)
        print(f"✅ Connected to MQTT broker at {self.broker}:{self.port}\n")

    @staticmethod
    def make_payload(value: float, tags: dict) -> str:
        """Build JSON payload for Influx line structure."""
        return json.dumps({
            "fields": {"value": round(value, 3)},
            "tags": tags,
            "timestamp": int(time.time() * 1000)
        })

    def generate_values(self, step: int) -> dict:
        """Generate realistic correlated and independent sensor data."""
        base_time = step * 0.15  # smooth variation per loop

        # Temperature group: correlated 18–26°C
        temp_base = 22.0 + 3 * math.sin(base_time) + random.uniform(-0.3, 0.3)

        # CO2 group: correlated 400–800 ppm
        co2_base = 550.0 + 120 * math.sin(base_time + 2) + random.uniform(-10, 10)

        # Humidity group: similar tags but different patterns
        humid_nyc = 45.0 + 10 * math.sin(base_time * 0.8 + 1) + random.uniform(-3, 3)
        humid_boston = 60.0 + 8 * math.sin(base_time * 1.1 + 2) + random.uniform(-3, 3)

        # Independent LA temp — different scale (Fahrenheit)
        temp_la = 70.0 + 10 * math.sin(base_time * 0.5) + random.uniform(-2, 2)

        return {
            "temperature": temp_base,
            "temp": temp_base + random.uniform(-0.1, 0.1),  # nearly identical (duplicate)
            "co2": co2_base,
            "carbon_dioxide": co2_base + random.uniform(-5, 5),  # nearly duplicate
            "humidity_nyc": humid_nyc,
            "humidity_boston": humid_boston,
            "temperature_f": temp_la
        }

    def publish_loop(self, interval_s: float = 2.0):
        """Continuously publish simulated IoT data."""
        print(f"📡 Publishing {len(TOPICS)} IoT topics every {interval_s}s...")
        print("\n🧠 Expected duplicate detections:")
        print("  - building/nyc/temperature ↔ sensors/manhattan/temp_sensor")
        print("  - air_quality/lab/co2_level ↔ environment/boston/carbon_dioxide")
        print("\n💡 Non-duplicates (similar tags but distinct):")
        print("  - building/nyc/humidity ↔ building/boston/humidity")
        print("  - weather/los_angeles/temperature\n")
        print("===========================================================\n")

        step = 0
        while True:
            values = self.generate_values(step)

            for topic, tags in TOPICS:
                sensor_type = tags.get("sensor_type", "")
                zone = tags.get("zone", "unknown")

                # Select appropriate value pattern
                if "temp" in sensor_type:
                    val = values.get("temp", 0)
                elif "temperature" in sensor_type and "fahrenheit" in tags.get("unit", "").lower():
                    val = values.get("temperature_f", 0)
                elif "temperature" in sensor_type:
                    val = values.get("temperature", 0)
                elif "co2" in sensor_type:
                    val = values.get("co2", 0)
                elif "carbon_dioxide" in sensor_type:
                    val = values.get("carbon_dioxide", 0)
                elif "humidity" in sensor_type and "nyc" in zone:
                    val = values.get("humidity_nyc", 0)
                elif "humidity" in sensor_type and "boston" in zone:
                    val = values.get("humidity_boston", 0)
                else:
                    val = random.uniform(0, 100)

                payload = self.make_payload(val, tags)
                full_topic = f"{topic}"
                self.client.publish(full_topic, payload)
                print(f"{full_topic:<55} → {val:7.2f} {tags['unit']}  [{tags['location']}]")

            # Debug progress print every 10 steps
            if step % 10 == 0 and step > 0:
                print(f"[DEBUG] Published {step * len(TOPICS)} messages so far...\n")

            print(f"--- Step {step} complete ---\n")
            step += 1
            time.sleep(interval_s)

    def start(self):
        """Start publishing after connection."""
        self.connect()
        self.publish_loop()


# ============================================================
# 🧪 ENTRY POINT
# ============================================================
if __name__ == "__main__":
    pub = MQTTPublisher("test.mosquitto.org", 1883)
    try:
        pub.start()
    except KeyboardInterrupt:
        print("\n🛑 Publisher stopped by user.")
