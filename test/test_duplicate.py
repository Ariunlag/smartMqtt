import sys
import asyncio
from pathlib import Path
from itertools import combinations

import numpy as np

# ---------- PATH SETUP ----------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]          # .../influxai_v2
BACKEND_ROOT = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_ROOT))

print("[DEBUG] PROJECT_ROOT =", PROJECT_ROOT)
print("[DEBUG] BACKEND_ROOT =", BACKEND_ROOT)

# ---------- IMPORT YOUR BACKEND ----------
from config import config  # type: ignore
from services.embedding_manager import embedding_manager  # type: ignore
from services.duplicate.duplicate_service import duplicate_service  # type: ignore
from services.query_manager import query_manager  # type: ignore


TOPIC_FILE = PROJECT_ROOT / "test" / "data" / "duplicate_topics.txt"
POINTS_FILE = PROJECT_ROOT / "test" / "data" / "duplicate_points.txt"


def load_topics():
    """
    Read duplicate_topics.txt

    Format:
        topic, key=value, key=value, ...
    """
    topic_to_tags: dict[str, dict[str, str]] = {}

    with TOPIC_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",") if p.strip()]
            topic = parts[0]
            tags: dict[str, str] = {}

            for item in parts[1:]:
                if "=" not in item:
                    continue
                k, v = item.split("=", 1)
                tags[k.strip()] = v.strip()

            topic_to_tags[topic] = tags

    return topic_to_tags


def load_points():
    """
    Read duplicate_points.txt

    Format:
        topic, v1, v2, v3, ...
    """
    topic_to_values: dict[str, list[float]] = {}

    with POINTS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",") if p.strip()]
            topic = parts[0]
            values = []

            for v in parts[1:]:
                try:
                    values.append(float(v))
                except ValueError:
                    print(f"[WARN] Skipping non-numeric value '{v}' for topic '{topic}'")

            topic_to_values[topic] = values

    return topic_to_values


def patch_query_manager(topic_to_values: dict[str, list[float]]):
    """
    Monkeypatch query_manager.get_last_points to read from our test mapping
    instead of InfluxDB.
    """

    async def fake_get_last_points(topic: str, limit: int = 100):
        values = topic_to_values.get(topic, [])
        if limit:
            values_cut = values[-limit:]
        else:
            values_cut = values
        # DuplicateService expects list[{"value": <number>}]
        return [{"value": v} for v in values_cut]

    # Patch the existing query_manager instance
    query_manager.get_last_points = fake_get_last_points  # type: ignore
    print("[DEBUG] Patched query_manager.get_last_points to use test data")


async def compute_embeddings(topic_to_tags: dict[str, dict[str, str]]):
    """
    Use your real EmbeddingManager to compute flattened topic embeddings.
    """
    topic_to_vec: dict[str, np.ndarray] = {}

    for topic, tags in topic_to_tags.items():
        print(f"[DEBUG] Embedding topic={topic} tags={tags}")
        vec = await embedding_manager.embed_flattened_topic(topic, tags)
        topic_to_vec[topic] = vec

    return topic_to_vec


async def main():
    # Load test data
    if not TOPIC_FILE.exists():
        print(f"[ERROR] Topic file not found: {TOPIC_FILE}")
        return
    if not POINTS_FILE.exists():
        print(f"[ERROR] Points file not found: {POINTS_FILE}")
        return

    topic_to_tags = load_topics()
    topic_to_values = load_points()

    print(f"[INFO] Loaded {len(topic_to_tags)} topics from {TOPIC_FILE}")
    print(f"[INFO] Loaded {len(topic_to_values)} time-series sets from {POINTS_FILE}")

    # Patch query_manager to return our test points
    patch_query_manager(topic_to_values)

    # Compute embeddings using your EmbeddingManager/model
    topic_to_vec = await compute_embeddings(topic_to_tags)

    topics = list(topic_to_vec.keys())
    id_thresh = getattr(config, "ID_THRESH", 0.9)
    print(f"\n[INFO] Using ID_THRESH={id_thresh}\n")

    results = []

    for t1, t2 in combinations(topics, 2):
        emb1 = topic_to_vec[t1]
        emb2 = topic_to_vec[t2]

        score = await duplicate_service.hybrid_score(t1, emb1, t2, emb2)
        results.append((t1, t2, score))

    # Sort by hybrid score descending
    results.sort(key=lambda x: x[2], reverse=True)

    # Print table
    print(f"{'Topic A':40} | {'Topic B':40} | Hybrid Score | Above Thresh?")
    print("-" * 110)
    for t1, t2, score in results:
        flag = "YES" if score >= id_thresh else "no"
        print(f"{t1[:40]:40} | {t2[:40]:40} | {score:11.4f} | {flag}")


if __name__ == "__main__":
    asyncio.run(main())
