# test/dupe_publisher.py
import json
import time
import random
import math

import paho.mqtt.client as mqtt
# --- Diverse topic structures to test real-world scenarios ---
TOPICS = [
    # Group 1: Temperature aliases (same meaning, different words/units)
    ("weather/nyc/temperature", {
        "location": "New York City",
        "unit": "celsius",
        "sensor_type": "temperature"
    }),
    ("sensors/manhattan/temp", {
        "location": "Manhattan",
        "unit": "°C",
        "sensor_type": "temp"   # shortened alias
    }),

    # Group 2: Humidity aliases
    ("building/chicago/humidity", {
        "location": "Chicago",
        "unit": "percent",
        "sensor_type": "humidity"
    }),
    ("env/illinois/moisture", {
        "location": "Illinois state",
        "unit": "%",
        "sensor_type": "moisture"
    }),

    # Group 3: CO2 aliases
    ("air_quality/office/co2_ppm", {
        "location": "Office",
        "unit": "ppm",
        "sensor_type": "carbon_dioxide"
    }),
    ("indoor/carbon_dioxide_level", {
        "location": "Indoors",
        "unit": "parts per million",
        "sensor_type": "co2"
    }),
    ("atmosphere/co2_concentration", {
        "location": "Conference Room",
        "unit": "ppm",
        "sensor_type": "co2_level"
    }),

    # Non-duplicates (unique sensors)
    ("lighting/office/brightness", {
        "location": "Main Office",
        "unit": "lux",
        "sensor_type": "illumination"
    }),
    ("power/building/consumption", {
        "location": "HQ Building",
        "unit": "watts",
        "sensor_type": "power_consumption"
    }),
    ("network/server/latency", {
        "alias": "Server ping latency",
        "location": "Datacenter",
        "unit": "ms",
        "sensor_type": "latency"
    }),
]

class MQTTPublisher:
    def __init__(self, broker: str, port: int):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.broker = broker
        self.port = port

    def connect(self):
        self.client.connect(self.broker, self.port)
        print(f"Connected to MQTT {self.broker}:{self.port}")

    @staticmethod
    def make_payload(value: float, tags: dict) -> str:
        return json.dumps({
            "fields": {"value": round(value, 3)},
            "tags": tags,
            "timestamp": int(time.time() * 1000)
        })

    def generate_values(self, step: int) -> dict:
        """Generate realistic sensor values with appropriate correlations."""
        base_time = step * 0.1  # Slow variation
        
        # Temperature group (correlated, 15-25°C range)
        temp_base = 20.0 + 3 * math.sin(base_time) + random.uniform(-0.5, 0.5)
        
        # Humidity group (correlated, 40-80% range)  
        humidity_base = 60.0 + 15 * math.sin(base_time + 1) + random.uniform(-2, 2)
        
        # CO2 group (correlated, 400-800 ppm range)
        co2_base = 600.0 + 150 * math.sin(base_time + 2) + random.uniform(-10, 10)
        
        # Independent sensors (no correlation)
        light_val = 500 + 400 * math.sin(base_time * 2) + random.uniform(-50, 50)  # 100-900 lux
        power_val = 1500 + 500 * math.sin(base_time * 0.5) + random.uniform(-100, 100)  # 1000-2000W
        latency_val = 25 + 20 * math.sin(base_time * 3) + random.uniform(-5, 5)  # 5-45ms
        
        return {
            "temperature": temp_base + random.uniform(-0.1, 0.1),
            "humidity": max(0, min(100, humidity_base + random.uniform(-1, 1))),
            "co2": max(300, co2_base + random.uniform(-5, 5)),
            "light": max(0, light_val),
            "power": max(0, power_val),
            "network": max(1, latency_val)
        }

    def publish_loop(self, interval_s: float = 2.0):
        print(f"Publishing {len(TOPICS)} diverse topics. Ctrl+C to stop.")
        print("Expected duplicates:")
        print("  - weather/nyc/temperature ↔ sensors/manhattan/temp")
        print("  - building/chicago/humidity ↔ env/illinois/moisture") 
        print("  - air_quality/office/co2_ppm ↔ indoor/carbon_dioxide_level ↔ atmosphere/co2_concentration")
        print()
        
        step = 0
        while True:
            values = self.generate_values(step)
            
            for topic, tags in TOPICS:
                # Map sensor type to value
                sensor_type = tags.get("sensor_type", "unknown")
                if sensor_type in values:
                    value = values[sensor_type]
                else:
                    value = random.uniform(0, 100)  # fallback
                
                payload = self.make_payload(value, tags)
                self.client.publish(topic, payload)
                print(f"{topic:<35} → value={value:6.1f} {tags['unit']}")
            
            print(f"--- Step {step} complete ---\n")
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
        print("Publisher stopped.")