# test/dupe_publisher.py
import json
import time
import random
import math
import paho.mqtt.client as mqtt


TOPICS = [
    # DUPLICATE GROUP 1: Temperature sensors
    ("building/nyc/temperature", {
        "location": "New York City",
        "zone": "office_floor_1",
        "sensor_type": "temperature",
        "unit": "celsius"
    }),
    ("sensors/manhattan/temp_sensor", {
        "location": "Manhattan",
        "zone": "office_floor1",           # small change
        "sensor_type": "temp",
        "unit": "°C"
    }),

    # DUPLICATE GROUP 2: CO2 sensors
    ("air_quality/lab/co2_level", {
        "location": "Boston Lab",
        "zone": "lab_A",
        "sensor_type": "co2",
        "unit": "ppm"
    }),
    ("environment/boston/carbon_dioxide", {
        "location": "Boston City Center",
        "zone": "labA",                    # small change
        "sensor_type": "carbon_dioxide",
        "unit": "parts_per_million"
    }),

    # NON-DUPES but with similar tags
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


class MQTTPublisher:
    def __init__(self, broker: str, port: int):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.broker = broker
        self.port = port

        # Stable per-topic biases so duplicates are close but not identical
        self.topic_bias = {
            "building/nyc/temperature": random.uniform(-0.08, 0.08),
            "sensors/manhattan/temp_sensor": random.uniform(-0.08, 0.08),
            "air_quality/lab/co2_level": random.uniform(-6, 6),
            "environment/boston/carbon_dioxide": random.uniform(-6, 6),
            "building/nyc/humidity": random.uniform(-1.0, 1.0),
            "building/boston/humidity": random.uniform(-1.0, 1.0),
            "weather/los_angeles/temperature": random.uniform(-0.6, 0.6),
        }

    def connect(self):
        self.client.connect(self.broker, self.port)
        print(f"Connected to MQTT broker at {self.broker}:{self.port}")

    @staticmethod
    def make_payload(value: float, tags: dict) -> str:
        return json.dumps({
            "fields": {"value": round(float(value), 3)},
            "tags": tags,
            "timestamp": int(time.time() * 1000)
        })

    def generate_true_signals(self, step: int) -> dict:
        t = step * 0.15

        # True temperature in Celsius (shared by temperature duplicates)
        true_temp_c = 22.0 + 3.0 * math.sin(t) + random.uniform(-0.15, 0.15)

        # True CO2 in ppm (shared by CO2 duplicates)
        true_co2_ppm = 550.0 + 120.0 * math.sin(t + 2.0) + random.uniform(-6, 6)

        # Non-dupe humidity patterns
        humid_nyc = 45.0 + 10.0 * math.sin(t * 0.8 + 1.0) + random.uniform(-2.0, 2.0)
        humid_boston = 60.0 + 8.0 * math.sin(t * 1.1 + 2.0) + random.uniform(-2.0, 2.0)

        # Independent LA temperature in Fahrenheit
        true_temp_la_f = 70.0 + 10.0 * math.sin(t * 0.5) + random.uniform(-1.5, 1.5)

        return {
            "true_temp_c": true_temp_c,
            "true_co2_ppm": true_co2_ppm,
            "humid_nyc": humid_nyc,
            "humid_boston": humid_boston,
            "temp_la_f": true_temp_la_f,
        }

    def value_for_topic(self, topic: str, tags: dict, signals: dict) -> float:
        unit = (tags.get("unit", "") or "").lower()

        # Temperature duplicate pair: both derived from the same true Celsius signal
        if topic == "building/nyc/temperature":
            base = signals["true_temp_c"]
            noise = random.uniform(-0.08, 0.08)
            return base + self.topic_bias[topic] + noise

        if topic == "sensors/manhattan/temp_sensor":
            base = signals["true_temp_c"]
            noise = random.uniform(-0.12, 0.12)
            return base + self.topic_bias[topic] + noise

        # CO2 duplicate pair: both derived from the same true ppm signal
        if topic == "air_quality/lab/co2_level":
            base = signals["true_co2_ppm"]
            noise = random.uniform(-4, 4)
            return base + self.topic_bias[topic] + noise

        if topic == "environment/boston/carbon_dioxide":
            base = signals["true_co2_ppm"]
            noise = random.uniform(-7, 7)
            return base + self.topic_bias[topic] + noise

        # Non-dupes
        if topic == "building/nyc/humidity":
            return signals["humid_nyc"] + self.topic_bias[topic]

        if topic == "building/boston/humidity":
            return signals["humid_boston"] + self.topic_bias[topic]

        if topic == "weather/los_angeles/temperature" and "fahrenheit" in unit:
            return signals["temp_la_f"] + self.topic_bias[topic]

        return random.uniform(0, 100)

    def publish_loop(self, interval_s: float = 2.0):
        print(f"Publishing {len(TOPICS)} topics every {interval_s}s")
        print("Expected duplicate detections:")
        print("  - building/nyc/temperature <-> sensors/manhattan/temp_sensor")
        print("  - air_quality/lab/co2_level <-> environment/boston/carbon_dioxide")
        print("Non-duplicates:")
        print("  - building/nyc/humidity <-> building/boston/humidity")
        print("  - weather/los_angeles/temperature")
        print("")

        step = 0
        while True:
            signals = self.generate_true_signals(step)

            for topic, tags in TOPICS:
                val = self.value_for_topic(topic, tags, signals)
                payload = self.make_payload(val, tags)

                self.client.publish(topic, payload)
                print(f"{topic:<55} -> {val:7.2f} {tags['unit']}  [{tags['location']}]")

            if step % 10 == 0 and step > 0:
                print(f"[DEBUG] Published {step * len(TOPICS)} messages so far")

            print(f"--- Step {step} complete ---")
            print("")
            step += 1
            time.sleep(interval_s)

    def start(self):
        self.connect()
        self.publish_loop()


if __name__ == "__main__":
    pub = MQTTPublisher("test.mosquitto.org", 1883)
    try:
        pub.start()
    except KeyboardInterrupt:
        print("Publisher stopped")
