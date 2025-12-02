import sys
from pathlib import Path
from collections import defaultdict

# ---------- PATH SETUP ----------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]          # .../influxai_v2
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

print("[DEBUG] PROJECT_ROOT =", PROJECT_ROOT)
print("[DEBUG] BACKEND_ROOT =", BACKEND_ROOT)

# ---------- IMPORT BACKEND MODULES ----------
# Import the tag_manager module itself so we can patch its global tagset_store
import services.tag_manager as tag_mod  # type: ignore
from services.embedding_manager import embedding_manager  # type: ignore

TOPIC_FILE = PROJECT_ROOT / "test" / "data" / "duplicate_topics.txt"


# ---------- FAKE TAG SET STORE ----------
class FakeTagSetStore:
    """
    Simple in-memory replacement for the real tagset_store.
    Matches the API used by TagManager: _data, add(), add_topic_to_set(), save().
    """
    def __init__(self):
        self._data = []

    def add(self, record: dict):
        self._data.append(record)

    def add_topic_to_set(self, set_id: str, topic: str):
        for s in self._data:
            if s["id"] == set_id:
                if topic not in s["topics"]:
                    s["topics"].append(topic)

    def save(self):
        # No-op: we don't persist anything in tests
        pass

    def get_all(self):
        return self._data


# ---------- PATCH MODULE GLOBAL STORE ----------
fake_store = FakeTagSetStore()
tag_mod.tagset_store = fake_store            # replace real store with fake
tag_manager = tag_mod.tag_manager            # use your existing TagManager instance


def load_topics_and_values():
    """
    Read duplicate_topics.txt and return a list of (topic, tag_value) pairs.

    We ignore the tag *keys* like 'location', 'zone', etc., and only keep values,
    because your system embeds only the tag values.
    """
    pairs: list[tuple[str, str]] = []

    with TOPIC_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",") if p.strip()]
            topic = parts[0]

            # remaining parts are "key=value"
            for item in parts[1:]:
                if "=" not in item:
                    continue
                _, value = item.split("=", 1)
                value = value.strip()
                if value:
                    pairs.append((topic, value))

    return pairs


def main():
    if not TOPIC_FILE.exists():
        print(f"[ERROR] Topic file not found: {TOPIC_FILE}")
        return

    pairs = load_topics_and_values()
    if not pairs:
        print("[ERROR] No (topic, tag_value) pairs loaded.")
        return

    # Reset fake store for a clean run
    fake_store._data = []

    model = embedding_manager.model
    print("\n[INFO] Using model:", type(model).__name__)
    print(f"[INFO] Loaded {len(pairs)} (topic, tag_value) pairs from {TOPIC_FILE}\n")

    set_id_to_values = defaultdict(list)
    set_id_to_topics = defaultdict(list)

    for topic, raw_value in pairs:
        # Your system embeds only the tag VALUE, normalized
        norm_value = embedding_manager._normalize_tag_value(raw_value)  # type: ignore

        # Encode a single tag value
        emb_vec = model.encode([norm_value])[0]

        # Use real TagManager logic with the fake store underneath
        set_id = tag_manager.process_tag(raw_value, emb_vec, topic)

        set_id_to_values[set_id].append(raw_value)
        set_id_to_topics[set_id].append(topic)

        print(f"[DEBUG] topic={topic:35} value='{raw_value}' -> set_id={set_id}")

    print("\n==== TAG GROUPS WITH 2+ TAG VALUES ====\n")

    cluster_count = 0
    for set_id in sorted(set_id_to_values.keys()):
        values = set_id_to_values[set_id]
        topics = set_id_to_topics[set_id]

        # Only show groups with at least 2 tag values (real clusters)
        if len(values) < 2:
            continue

        cluster_count += 1
        print(f"{set_id}:")
        print("  tag_values:", values)
        print("  topics:    ", topics)
        print()

    if cluster_count == 0:
        print("No multi-tag clusters found (all sets had only one tag value).")

    print("Done.")


if __name__ == "__main__":
    main()
