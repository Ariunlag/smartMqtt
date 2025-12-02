import sys
from pathlib import Path
import numpy as np

# ---------- Resolve paths ----------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]         # .../influxai_v2
BACKEND_ROOT = PROJECT_ROOT / "backend"

# Add backend to sys.path so "services" can be imported
sys.path.insert(0, str(BACKEND_ROOT))

print("[DEBUG] PROJECT_ROOT =", PROJECT_ROOT)
print("[DEBUG] BACKEND_ROOT =", BACKEND_ROOT)

# Now we can import from backend/services
from services.embedding_manager import embedding_manager  # type: ignore


def cosine(a, b) -> float:
    """Simple cosine similarity."""
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def load_pairs(path: Path):
    """Load comma-separated text pairs from a txt file."""
    pairs: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 2:
                print(f"[WARN] Skipping invalid line: {line}")
                continue

            pairs.append((parts[0], parts[1]))
    return pairs


def main():
    txt_file = PROJECT_ROOT / "test" / "data" / "similarity.txt"
    if not txt_file.exists():
        print(f"[ERROR] Input file not found: {txt_file}")
        return

    pairs = load_pairs(txt_file)
    if not pairs:
        print("[ERROR] No valid pairs loaded from file.")
        return

    # Use the SAME model instance that EmbeddingManager uses
    model = embedding_manager.model

    print("\nUsing model:", type(model).__name__)
    print(f"Loaded {len(pairs)} pairs from {txt_file}\n")

    print(f"{'Text A':30} | {'Text B':30} | Similarity")
    print("-" * 80)

    for text_a, text_b in pairs:
        # STEmbeddingModel.encode expects a list of texts
        emb_a, emb_b = model.encode([text_a, text_b])

        sim = cosine(emb_a, emb_b)
        print(f"{text_a[:30]:30} | {text_b[:30]:30} | {sim:.4f}")


if __name__ == "__main__":
    main()
