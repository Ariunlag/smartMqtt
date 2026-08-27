"""Build registry-defined embedding evidence for every stream key/value pair."""

from __future__ import annotations

import hashlib
import json

from .domain import PairIdentity, PairRepresentation
from .evidence import render_pair_evidence
from .profiling import StreamProfile


class PairRepresentationBuilder:
    """Preserve pair identity while rendering deterministic evidence texts."""

    @staticmethod
    def fingerprint(profile: StreamProfile) -> str:
        """Fingerprint recommendation-relevant structure and categorical values.

        Fast-changing numeric field readings remain excluded from the fingerprint so
        telemetry variation does not rematerialize pair embeddings on every sample.
        Numeric is inferred from datatype only; it is not a separate evidence channel
        or duplicated boolean property.
        """
        rows = [
            (
                entry.source,
                entry.normalized_key,
                entry.value_type,
                (
                    None
                    if entry.source == "field" and entry.value_type == "numeric"
                    else entry.normalized_value
                ),
            )
            for entry in profile.entries
        ]
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def build(
        profile: StreamProfile,
        *,
        canonical_topic: str,
        original_topic: str,
        representation_version: int,
    ) -> tuple[PairRepresentation, ...]:
        seen: set[PairIdentity] = set()
        records = []
        for entry in profile.entries:
            identity = PairIdentity(
                source=entry.source,
                normalized_key=entry.normalized_key,
                datatype=entry.value_type,
            )
            if identity in seen:
                raise ValueError(
                    f"Duplicate normalized pair identity: {identity.value}"
                )
            seen.add(identity)
            records.append(
                PairRepresentation(
                    canonical_topic=canonical_topic,
                    original_topic=original_topic,
                    identity=identity,
                    raw_key=entry.key,
                    raw_value=entry.value,
                    normalized_key=entry.normalized_key,
                    normalized_value=entry.normalized_value,
                    datatype=entry.value_type,
                    representation_version=representation_version,
                    texts=render_pair_evidence(entry),
                )
            )
        return tuple(records)
