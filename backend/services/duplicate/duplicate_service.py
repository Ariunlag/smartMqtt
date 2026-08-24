import math

import numpy as np
from config import config
from scipy.stats import pearsonr
from services.query_manager import query_manager


class DuplicateService:
    """Provides similarity calculations for duplicate detection."""

    def __init__(self, min_points: int = config.MIN_POINTS):
        self.min_points = min_points

    def cosine(self, a, b) -> float:
        """Compute cosine similarity between two vectors."""
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denominator == 0.0 or not math.isfinite(denominator):
            return 0.0
        result = float(np.dot(a, b) / denominator)
        return result if math.isfinite(result) else 0.0

    async def hybrid_score(self, topic_a, emb_a, topic_b, emb_b) -> float:
        """Compute cosine + correlation hybrid score between two topics."""
        cosine = self.cosine(emb_a, emb_b)

        vals_a = await query_manager.get_last_points(topic_a, limit=100)
        vals_b = await query_manager.get_last_points(topic_b, limit=100)

        # Align by timestamp so correlation compares values at the same instants
        # instead of by list position (which is meaningless when the two streams
        # have different sampling rates or offsets).
        series_a = {
            p["time"]: p["value"]
            for p in vals_a
            if isinstance(p["value"], (int, float))
        }
        series_b = {
            p["time"]: p["value"]
            for p in vals_b
            if isinstance(p["value"], (int, float))
        }
        shared_times = sorted(series_a.keys() & series_b.keys())
        values_a = [series_a[t] for t in shared_times]
        values_b = [series_b[t] for t in shared_times]
        n = len(shared_times)

        if n < self.min_points:
            return cosine

        if np.ptp(values_a) == 0 or np.ptp(values_b) == 0:
            corr = 0.0
        else:
            corr, _ = pearsonr(values_a, values_b)
            if not math.isfinite(float(corr)):
                corr = 0.0
        corr_score = (corr + 1.0) / 2.0
        weight = min(0.5, n / 200.0)
        score = (1 - weight) * cosine + weight * corr_score
        return float(score) if math.isfinite(float(score)) else 0.0


# Singleton instance
duplicate_service = DuplicateService()
