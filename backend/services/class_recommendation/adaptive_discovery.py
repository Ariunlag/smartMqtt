"""Bounded approximate candidates, followed by the original pair-level scorer.

Random projection neighborhoods are a deterministic retrieval heuristic, not an
exact nearest-neighbor index. Missing edges never certify a complete-link merge.
"""

from dataclasses import asdict, dataclass
import hashlib
from time import perf_counter

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from .adaptive_evidence import weighted_score


@dataclass(frozen=True)
class DiscoveryConfig:
    exact_limit: int = 192
    neighbors: int = 32
    projections: int = 8
    window: int = 8
    max_group_size: int = 64
    seed: int = 731

    def __post_init__(self):
        if self.exact_limit < 0 or min(self.neighbors, self.projections, self.window) < 1 or self.max_group_size < 2:
            raise ValueError("Invalid discovery budget")


def representations(topics, material, registry, weights):
    """Centroids only retrieve candidates; exact scoring retains individual pairs."""
    spaces = []
    for key in registry.active_ids:
        if weights.get(key, 0) <= 0:
            continue
        vectors, positions = [], []
        dimension = None
        for i, topic in enumerate(topics):
            records = material[topic].get(key, [])
            provider = registry.providers[key]
            if hasattr(provider, "retrieval_records"):
                records = provider.retrieval_records(records)
            valid = [r for r in records if r.get("embedding") is not None
                     and r.get("provider_version", registry.material_version(key)) == registry.material_version(key)]
            if not valid:
                continue
            rows = np.asarray([r["embedding"] for r in valid], dtype=np.float32)
            if rows.ndim != 2 or not np.isfinite(rows).all():
                continue
            vector = rows.mean(axis=0)
            norm = np.linalg.norm(vector)
            if not norm or (dimension is not None and len(vector) != dimension):
                continue
            dimension = len(vector)
            vectors.append(vector / norm)
            positions.append(i)
        if vectors:
            full = np.zeros((len(topics), dimension), dtype=np.float32)
            mask = np.zeros(len(topics), dtype=bool)
            full[positions], mask[positions] = vectors, True
            spaces.append((key, full, mask, weights[key]))
    return spaces


def candidate_neighbors(topics, material, registry, weights, config):
    n = len(topics)
    pools = [set() for _ in topics]
    spaces = representations(topics, material, registry, weights)
    for key, vectors, mask, _ in spaces:
        salt = int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big")
        rng = np.random.default_rng(config.seed + salt)
        positions = np.flatnonzero(mask)
        projections = vectors[positions] @ rng.normal(size=(vectors.shape[1], config.projections)).astype(np.float32)
        for column in range(config.projections):
            # Random deterministic tie order avoids lexical neighbors dominating
            # repeated/common metadata such as identical tag-key sets.
            order = positions[np.lexsort((rng.random(len(positions)), projections[:, column]))]
            for offset in range(1, min(config.window + 1, len(order))):
                for a, b in zip(order[:-offset], order[offset:], strict=True):
                    pools[int(a)].add(int(b))
                    pools[int(b)].add(int(a))
    neighbors = []
    for i, pool in enumerate(pools):
        candidates = np.asarray(sorted(pool), dtype=int)
        numerator, denominator = np.zeros(len(candidates)), np.zeros(len(candidates))
        for _, vectors, mask, weight in spaces:
            if not mask[i]:
                continue
            available = mask[candidates]
            numerator += weight * available * (vectors[candidates] @ vectors[i] + 1) / 2
            denominator += weight * available
        scores = numerator / np.maximum(denominator, 1e-12)
        chosen = np.lexsort((candidates, -scores))[:config.neighbors]
        neighbors.append(tuple(int(v) for v in candidates[chosen]))
    return neighbors


def discover(material, registry, weights, threshold, config, compare=None):
    started = perf_counter()
    topics = sorted(material)
    n = len(topics)
    compare = compare or (lambda a, b: registry.compare(material[a], material[b]))
    exact = n <= config.exact_limit
    scores = {}
    if exact:
        pairs = ((i, j) for i in range(n) for j in range(i + 1, n))
        neighbors = None
    else:
        neighbors = candidate_neighbors(topics, material, registry, weights, config)
        pairs = sorted({(min(i, j), max(i, j)) for i, row in enumerate(neighbors) for j in row})
    for i, j in pairs:
        score = weighted_score(compare(topics[i], topics[j]), weights)
        scores[(i, j)] = score if score is not None else 0.
    if exact and n >= 2:
        distances = np.ones((n, n))
        np.fill_diagonal(distances, 0.)
        for (i, j), score in scores.items():
            distances[i, j] = distances[j, i] = 1 - score
        labels = AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="complete",
                                         distance_threshold=1 - threshold).fit_predict(distances)
        clusters = [[topics[i] for i in range(n) if labels[i] == label] for label in sorted(set(labels))]
    else:
        # Bounded complete-link graph merging. An absent edge is unknown, never
        # assumed similar; this cannot produce single-link chaining false positives.
        owner = list(range(n))
        groups = {i: {i} for i in range(n)}
        for (i, j), score in sorted(scores.items(), key=lambda row: (-row[1], row[0])):
            if score <= threshold:
                break
            a, b = owner[i], owner[j]
            if a == b or len(groups[a]) + len(groups[b]) > config.max_group_size:
                continue
            if all(scores.get((min(x, y), max(x, y)), -1) > threshold for x in groups[a] for y in groups[b]):
                for member in groups[b]:
                    owner[member] = a
                groups[a].update(groups.pop(b))
        clusters = [[topics[i] for i in sorted(group)] for group in groups.values()]
    metrics = {"mode": "exact" if exact else "approximate", "algorithm": "complete-linkage" if exact else "projection-neighborhood-complete-link",
               "topic_count": n, "scored_pairs": len(scores), "possible_pairs": n * (n - 1) // 2,
               "elapsed_seconds": perf_counter() - started, "config": asdict(config)}
    adjacency = {topic: [] for topic in topics}
    for (i, j), score in scores.items():
        adjacency[topics[i]].append((topics[j], score))
        adjacency[topics[j]].append((topics[i], score))
    adjacency = {t: [other for other, _ in sorted(rows, key=lambda r: (-r[1], r[0]))[:config.neighbors]]
                 for t, rows in adjacency.items()}
    return [c for c in clusters if len(c) >= 2], metrics, adjacency, scores
