"""Build five independent embedding views for every stream key/value pair."""

from __future__ import annotations

import hashlib
import json

from .domain import PairIdentity, PairRepresentation
from .profiling import StreamProfile


class PairRepresentationBuilder:
    """Preserve pair identity while rendering deterministic view texts."""

    @staticmethod
    def fingerprint(profile: StreamProfile) -> str:
        """Fingerprint recommendation-relevant structure and categorical values.

        Numeric readings are deliberately represented by datatype rather than
        their rapidly changing value. The numeric value channel is sampled when
        the representation is created; numeric-key and schema remain the stable
        measurement evidence.
        """
        rows = [
            (
                entry.source,
                entry.normalized_key,
                entry.value_type,
                None if entry.is_numeric else entry.normalized_value,
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
            texts = [
                ("key", entry.normalized_key),
                ("value", entry.normalized_value),
                ("key_value", f"{entry.normalized_key}: {entry.normalized_value}"),
                ("schema", f"{entry.normalized_key}: {entry.value_type}"),
            ]
            if entry.is_numeric:
                texts.append(("numeric_key", entry.normalized_key))
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
                    is_numeric=entry.is_numeric,
                    representation_version=representation_version,
                    texts=tuple(texts),
                )
            )
        return tuple(records)
