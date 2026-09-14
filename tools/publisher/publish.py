"""Run this file: subscribe all topics, then publish every two seconds. Ctrl+C stops."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import time
from urllib.request import Request, urlopen

BROKER = "localhost"
PORT = 1883
BACKEND = "http://localhost:8000/api"
INTERVAL = 2
DATASET = Path(__file__).with_name("dataset.json")


def load_topics():
    topics = json.loads(DATASET.read_text(encoding="utf-8"))
    if not topics or len({s["topic"] for s in topics}) != len(topics):
        raise ValueError("Every sensor needs a unique topic")
    for sensor in topics:
        if not sensor["topic"] or any(c in sensor["topic"] for c in ("+", "#", "\0")):
            raise ValueError("Use exact MQTT topics without wildcards")
        if not sensor["tags"] or not sensor["fields"]:
            raise ValueError("Every sensor needs tags and fields")
    return topics


def make_payload(sensor, step, index):
    fields = {}
    for name, base in sensor["fields"].items():
        if type(base) in (int, float):
            # Each sensor has its own rhythm; metadata never changes with a reading.
            rng = random.Random(f"{index}:{name}:{step}")
            amplitude = max(abs(base)*.04, .1)
            value = base + amplitude*math.sin(step*.18 + index*.71) + rng.uniform(-amplitude*.1, amplitude*.1)
            fields[name] = round(value) if type(base) is int else round(value, 3)
        else:
            fields[name] = base
    return {"tags": dict(sensor["tags"]), "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", default=BROKER)
    parser.add_argument("--backend", default=BACKEND)
    parser.add_argument("--rounds", type=int, default=0, help="0 = continuous (default)")
    parser.add_argument("--dry-run", action="store_true", help="Preview all payloads without connecting")
    args = parser.parse_args(argv)
    if args.rounds < 0:
        parser.error("rounds must be zero or positive")
    topics = load_topics()
    if args.dry_run:
        for index, sensor in enumerate(topics):
            print(json.dumps({"topic": sensor["topic"], "payload": make_payload(sensor, 0, index)}, ensure_ascii=False))
        return

    import paho.mqtt.client as mqtt
    backend = args.backend.rstrip("/")
    if not backend.endswith("/api"):
        backend += "/api"
    for sensor in topics:
        request = Request(backend+"/subscribe", data=json.dumps({"topic": sensor["topic"]}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=15) as response:
            response.read()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.broker, PORT, 60)
    client.loop_start()
    print(f"Publishing {len(topics)} sensors every {INTERVAL}s. Ctrl+C stops.", flush=True)
    step = 0
    try:
        while args.rounds == 0 or step < args.rounds:
            for index, sensor in enumerate(topics):
                body = make_payload(sensor, step, index)
                info = client.publish(sensor["topic"], json.dumps(body, allow_nan=False), qos=1)
                info.wait_for_publish(timeout=10)
                if not info.is_published():
                    raise RuntimeError(f"Message was not acknowledged: {sensor['topic']}")
                print(f"{sensor['topic']} -> {body['fields']} | {body['tags']}", flush=True)
            step += 1
            print(f"Update {step}: all {len(topics)} topics published.", flush=True)
            if args.rounds == 0 or step < args.rounds:
                time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("Publisher stopped.", flush=True)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
