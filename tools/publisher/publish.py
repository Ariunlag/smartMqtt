"""Continuously publish SmartMQTT datasets with random numeric sensor noise.

By default this publishes every topic forever. Press Ctrl+C to stop.
Use --dataset to switch between the bundled test datasets.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time
from urllib.request import Request, urlopen

BROKER = "localhost"
PORT = 1883
BACKEND = "http://localhost:8000/api"
INTERVAL = 2.0
NOISE_PCT = 0.03
SEED = 42
DATASET = Path(__file__).with_name("dataset.json")


def load_topics(dataset=DATASET):
    dataset_path = Path(dataset)
    topics = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not topics or len({sensor["topic"] for sensor in topics}) != len(topics):
        raise ValueError("Every sensor needs a unique topic")

    for sensor in topics:
        if set(sensor) != {"topic", "tags", "fields"}:
            raise ValueError("Every sensor needs exactly topic, tags, and fields")
        if not sensor["topic"] or any(
            char in sensor["topic"] for char in ("+", "#", "\0")
        ):
            raise ValueError("Use exact MQTT topics without wildcards")
        if not sensor["tags"] or not sensor["fields"]:
            raise ValueError("Every sensor needs tags and fields")

    return topics


def make_payload(sensor, step, index, *, seed=SEED, noise_pct=NOISE_PCT):
    fields = {}

    for name, base in sensor["fields"].items():
        # bool is intentionally excluded even though bool is an int subclass.
        if type(base) in (int, float):
            rng = random.Random(f"{seed}:{index}:{name}:{step}")
            sigma = max(abs(base) * noise_pct, 0.05)
            value = base + rng.gauss(0.0, sigma)
            fields[name] = round(value) if type(base) is int else round(value, 3)
        else:
            fields[name] = base

    return {
        "tags": dict(sensor["tags"]),
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", default=BROKER)
    parser.add_argument("--backend", default=BACKEND)
    parser.add_argument(
        "--dataset",
        default=str(DATASET),
        help="Path to a SmartMQTT JSON dataset",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=INTERVAL,
        help="Seconds between complete publish rounds",
    )
    parser.add_argument(
        "--noise-pct",
        type=float,
        default=NOISE_PCT,
        help="Gaussian noise standard deviation as a fraction of each numeric base value",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help="Random seed; use the same seed for fair branch comparisons",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=0,
        help="0 = continuous until Ctrl+C",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview one generated payload per topic without connecting",
    )
    args = parser.parse_args(argv)

    if args.rounds < 0:
        parser.error("rounds must be zero or positive")
    if args.interval < 0:
        parser.error("interval must be zero or positive")
    if args.noise_pct < 0:
        parser.error("noise-pct must be zero or positive")

    topics = load_topics(args.dataset)

    if args.dry_run:
        for index, sensor in enumerate(topics):
            print(
                json.dumps(
                    {
                        "topic": sensor["topic"],
                        "payload": make_payload(
                            sensor,
                            0,
                            index,
                            seed=args.seed,
                            noise_pct=args.noise_pct,
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        return

    import paho.mqtt.client as mqtt

    backend = args.backend.rstrip("/")
    if not backend.endswith("/api"):
        backend += "/api"

    for sensor in topics:
        request = Request(
            backend + "/subscribe",
            data=json.dumps({"topic": sensor["topic"]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            response.read()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.broker, PORT, 60)
    client.loop_start()

    print(
        f"Publishing {len(topics)} sensors from {Path(args.dataset).name} "
        f"every {args.interval:g}s with {args.noise_pct:.1%} random noise "
        f"(seed={args.seed}). Ctrl+C stops.",
        flush=True,
    )

    step = 0
    try:
        while args.rounds == 0 or step < args.rounds:
            for index, sensor in enumerate(topics):
                body = make_payload(
                    sensor,
                    step,
                    index,
                    seed=args.seed,
                    noise_pct=args.noise_pct,
                )
                info = client.publish(
                    sensor["topic"],
                    json.dumps(body, allow_nan=False),
                    qos=1,
                )
                info.wait_for_publish(timeout=10)

                if not info.is_published():
                    raise RuntimeError(
                        f"Message was not acknowledged: {sensor['topic']}"
                    )

                print(
                    f"{sensor['topic']} -> {body['fields']} | {body['tags']}",
                    flush=True,
                )

            step += 1
            print(
                f"Update {step}: all {len(topics)} topics published.",
                flush=True,
            )

            if args.rounds == 0 or step < args.rounds:
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("Publisher stopped.", flush=True)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
