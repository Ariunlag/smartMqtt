import numpy as np
from scipy.stats import pearsonr
from services.query_manager import query_manager
from config import config


class DuplicateService:
    """Provides similarity calculations for duplicate detection."""

    def __init__(self, min_points: int = config.MIN_POINTS):
        self.min_points = min_points

    def cosine(self, a, b) -> float:
        """Compute cosine similarity between two vectors."""
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    async def hybrid_score(self, topic_a, emb_a, topic_b, emb_b) -> float:
        """Compute cosine + correlation hybrid score between two topics."""
        cosine = self.cosine(emb_a, emb_b)

        vals_a = await query_manager.get_last_points(topic_a, limit=100)
        vals_b = await query_manager.get_last_points(topic_b, limit=100)
        values_a = [p["value"] for p in vals_a if isinstance(p["value"], (int, float))]
        values_b = [p["value"] for p in vals_b if isinstance(p["value"], (int, float))]
        n = min(len(values_a), len(values_b))

        if n < self.min_points:
            return cosine

        corr, _ = pearsonr(values_a[:n], values_b[:n])
        corr_score = (corr + 1.0) / 2.0
        weight = min(0.5, n / 200.0)
        return (1 - weight) * cosine + weight * corr_score


# Singleton instance
duplicate_service = DuplicateService()
