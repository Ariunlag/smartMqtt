"""Extensible evidence providers. Vectors stay inside their own model spaces."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from collections import OrderedDict
from typing import Protocol

import numpy as np
from scipy.optimize import linear_sum_assignment


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def key_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip().lower()


def value_text(value) -> str:
    # Preserve signs and punctuation in values (e.g. -5, part-123).
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ProviderDefinition:
    evidence_id: str
    label: str
    scope: str
    version: str = "1"
    kind: str = "embedding"
    active: bool = False
    comparator: str = "aligned-cosine-v1"
    refresh_policy: str = "topic-or-tags-change"


class EvidenceProvider(Protocol):
    definition: ProviderDefinition

    def materialize(self, topic: str, tags: dict, encode) -> list[dict]: ...

    def compare(self, left: list[dict], right: list[dict]) -> dict: ...


def cosine_matrix(left, right):
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[1]:
        raise ValueError("Incompatible evidence dimensions")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Non-finite evidence")
    an, bn = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
    denominator = an[:, None] * bn[None, :]
    return np.clip(np.divide(a @ b.T, denominator, out=np.zeros_like(denominator),
                             where=denominator > 0), -1, 1)


class TextProvider:
    def __init__(self, evidence_id, label, scope, *, min_match_similarity=0.75):
        comparator = (
            "cosine-v1" if scope == "stream" else "strong-aligned-cosine-v2"
        )
        self.definition = ProviderDefinition(
            evidence_id,
            label,
            scope,
            active=True,
            comparator=comparator,
        )
        self.min_match_similarity = float(min_match_similarity)
        if not 0.0 <= self.min_match_similarity <= 1.0:
            raise ValueError("min_match_similarity must be between 0 and 1")

    def text_records(self, topic, tags):
        if self.definition.scope == "stream":
            pairs = [("topic", topic.replace("/", " "), {})]
        else:
            pairs = []
            for key, value in sorted(tags.items()):
                rendered_key, rendered_value = key_text(key), value_text(value)
                text = {"tag_key": rendered_key, "tag_value": rendered_value,
                        "tag_key_value": f"{rendered_key}: {rendered_value}"}[self.definition.evidence_id]
                pairs.append((key, text, {"key": key, "value": value}))
        return pairs

    def materialize(self, topic, tags, encode):
        pairs = self.text_records(topic, tags)
        vectors = encode([text for _, text, _ in pairs]) if pairs else []
        return [dict(entity=entity, embedding=vector,
                     payload={"text": text, **payload})
                for (entity, text, payload), vector in zip(pairs, vectors, strict=True)]

    def compare(self, left, right):
        if not left or not right:
            return {"score": None, "status": "missing", "coverage": 0., "matches": []}

        matrix = cosine_matrix(
            [r["embedding"] for r in left],
            [r["embedding"] for r in right],
        )

        # Each channel chooses its own one-to-one alignment, but pair channels keep
        # only semantically strong matches. Forced low-similarity assignments are not
        # evidence: they are omitted from the score and exposed only through reduced
        # coverage. This lets one real common tag (for example Chicago) contribute
        # without averaging it together with unrelated metadata.
        rows, cols = linear_sum_assignment(matrix, maximize=True)
        aligned = [
            (
                int(i),
                int(j),
                float((matrix[i, j] + 1.0) / 2.0),
            )
            for i, j in zip(rows.tolist(), cols.tolist(), strict=True)
        ]

        if self.definition.scope == "stream":
            kept = aligned
        else:
            kept = [
                item
                for item in aligned
                if item[2] >= self.min_match_similarity
            ]

        coverage = len(kept) / max(len(left), len(right))
        score = float(np.mean([item[2] for item in kept])) if kept else 0.0
        return {
            "score": score,
            "status": "available",
            "coverage": coverage,
            "matches": [
                {
                    "left": left[i]["payload"],
                    "right": right[j]["payload"],
                    "similarity": similarity,
                }
                for i, j, similarity in kept
            ],
        }


class ProviderRegistry:
    def __init__(self, providers=None, *, model_id="BAAI/bge-small-en-v1.5"):
        self.providers = {}
        self.model_id = model_id
        for provider in providers if providers is not None else (
            TextProvider("topic_text", "Topic meaning", "stream"),
            TextProvider("tag_key", "Tag keys", "pair"),
            TextProvider("tag_value", "Tag values", "pair"),
            TextProvider("tag_key_value", "Tag key + value", "pair"),
        ):
            self.register(provider)

    def register(self, provider):
        key = provider.definition.evidence_id
        if key in self.providers:
            raise ValueError(f"Duplicate provider: {key}")
        self.providers[key] = provider

    @property
    def active_ids(self):
        return tuple(k for k, p in self.providers.items() if p.definition.active)

    @property
    def manifest_id(self):
        return fingerprint({"model": self.model_id, "scoring": "masked-coverage-v1",
                            "providers": [asdict(self.providers[k].definition) for k in self.active_ids]})

    def catalog(self):
        return [asdict(p.definition) for p in self.providers.values()]

    def material_version(self, key):
        provider = self.providers[key]
        if isinstance(provider, TextProvider):
            return fingerprint({"model": self.model_id, "provider": asdict(provider.definition)})
        return provider.definition.version

    def compare(self, left, right):
        result = {}
        for key, provider in self.providers.items():
            version = self.material_version(key)
            a, b = left.get(key, []), right.get(key, [])
            if any(r.get("provider_version", version) != version for r in [*a, *b]):
                result[key] = {"score": None, "status": "incompatible", "coverage": 0., "matches": []}
            else:
                try:
                    row = provider.compare(a, b)
                    if row.get("status") == "available":
                        score, coverage = row.get("score"), row.get("coverage", 1.)
                        if not (isinstance(score, (int, float)) and np.isfinite(score)
                                and 0 <= score <= 1 and np.isfinite(coverage) and 0 <= coverage <= 1):
                            raise ValueError("Provider scores and coverage must be finite in [0, 1]")
                    result[key] = row
                except (ValueError, TypeError):
                    result[key] = {"score": None, "status": "incompatible", "coverage": 0., "matches": []}
        return result


class CachedEncoder:
    """Bounded per-model text cache; encode misses together and preserve pair records."""

    def __init__(self, model, maxsize=8192):
        self.model = model
        self.maxsize = maxsize
        self.cached = OrderedDict()

    def __call__(self, texts):
        resolved = {text: self.cached[text] for text in texts if text in self.cached}
        missing = [text for text in dict.fromkeys(texts) if text not in resolved]
        if missing:
            vectors = self.model.encode(missing)
            if len(vectors) != len(missing):
                raise ValueError("Embedding model returned an incorrect batch length")
            for text, vector in zip(missing, vectors, strict=True):
                row = np.asarray(vector, dtype=float)
                if row.ndim != 1 or not row.size or not np.isfinite(row).all():
                    raise ValueError("Invalid embedding vector")
                resolved[text] = row.tolist()
        for text, vector in resolved.items():
            self.cached[text] = vector
            self.cached.move_to_end(text)
            if len(self.cached) > self.maxsize:
                self.cached.popitem(last=False)
        return [list(resolved[text]) for text in texts]


def weighted_score(evidence: dict, weights: dict) -> float | None:
    available = [(weights.get(key, 0.), item) for key, item in evidence.items()
                 if item.get("status") == "available" and item.get("score") is not None]
    total = sum(w for w, _ in available)
    if total <= 0:
        return None
    return sum(w * item["score"] * item.get("coverage", 1.) for w, item in available) / total
