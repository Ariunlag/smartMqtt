"""Persistence adapters for recommendation evidence, versions, and audit."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict

from services.database.postgres import postgres_client
from services.database.vector import deterministic_vector_identity, vector_store

from .domain import (
    REPRESENTATION_CONTRACT_VERSION,
    ClassPairPrototype,
    PairEmbeddingRecord,
    PairIdentity,
    PairRepresentation,
)
from .evidence import PAIR_EVIDENCE_IDS

PAIR_EMBEDDING_COLLECTION = "class_pair_embeddings"
PAIR_PROTOTYPE_COLLECTION = "class_pair_prototypes"
STREAM_CONTEXT_PROTOTYPE_COLLECTION = "class_stream_context_prototypes"
_PAIR_EVIDENCE_ORDER = {
    evidence_id: index for index, evidence_id in enumerate(PAIR_EVIDENCE_IDS)
}


def _evidence_sort_key(item) -> tuple[int, str]:
    evidence_id = item[0]
    return (_PAIR_EVIDENCE_ORDER.get(evidence_id, len(_PAIR_EVIDENCE_ORDER)), evidence_id)


class PairEmbeddingStore:
    """Persist raw pair embedding evidence in PostgreSQL + pgvector."""

    def __init__(self, client=vector_store) -> None:
        self.client = client

    @staticmethod
    def _identity(topic: str, identity: PairIdentity, view: str) -> str:
        return deterministic_vector_identity(
            PAIR_EMBEDDING_COLLECTION,
            topic,
            identity.source,
            identity.normalized_key,
            identity.datatype,
            view,
        )

    def replace_topic(
        self, topic: str, records: tuple[PairEmbeddingRecord, ...]
    ) -> None:
        self.remove_topic(topic)
        for record in records:
            representation = record.representation
            for view, vector in record.vectors:
                self.client.upsert(
                    PAIR_EMBEDDING_COLLECTION,
                    self._identity(topic, representation.identity, view),
                    list(vector),
                    {
                        "canonical_topic": topic,
                        "original_topic": representation.original_topic,
                        "source": representation.identity.source,
                        "raw_key": representation.raw_key,
                        "raw_value": str(representation.raw_value),
                        "normalized_key": representation.normalized_key,
                        "normalized_value": representation.normalized_value,
                        "datatype": representation.datatype,
                        "representation_version": representation.representation_version,
                        "representation_view": view,
                        "representation_text": representation.text_for(view),
                    },
                )

    @staticmethod
    def _records_from_points(topic: str, points) -> tuple[PairEmbeddingRecord, ...]:
        grouped: dict[PairIdentity, dict] = {}
        for point in points:
            payload = point.payload
            identity = PairIdentity(
                payload["source"], payload["normalized_key"], payload["datatype"]
            )
            row = grouped.setdefault(
                identity, {"payload": payload, "vectors": [], "texts": []}
            )
            row["vectors"].append((payload["representation_view"], tuple(point.vector)))
            row["texts"].append(
                (
                    payload["representation_view"],
                    payload.get("representation_text", ""),
                )
            )

        records = []
        for identity in sorted(grouped):
            row = grouped[identity]
            payload = row["payload"]
            texts = tuple(sorted(row["texts"], key=_evidence_sort_key))
            records.append(
                PairEmbeddingRecord(
                    PairRepresentation(
                        canonical_topic=topic,
                        original_topic=payload.get("original_topic", topic),
                        identity=identity,
                        raw_key=payload.get("raw_key", identity.normalized_key),
                        raw_value=payload.get("raw_value", ""),
                        normalized_key=identity.normalized_key,
                        normalized_value=payload.get("normalized_value", ""),
                        datatype=identity.datatype,
                        representation_version=int(payload["representation_version"]),
                        texts=texts,
                    ),
                    tuple(sorted(row["vectors"], key=_evidence_sort_key)),
                )
            )
        return tuple(records)

    def get_topic(self, topic: str) -> tuple[PairEmbeddingRecord, ...]:
        points = self.client.points_where(
            PAIR_EMBEDDING_COLLECTION,
            {"canonical_topic": topic},
        )
        return self._records_from_points(topic, points)

    def get_topics(
        self, topics: list[str] | tuple[str, ...]
    ) -> dict[str, tuple[PairEmbeddingRecord, ...]]:
        """Load pair evidence for many topics in one database round-trip."""
        selected = tuple(sorted(set(topics)))
        result = {topic: () for topic in selected}
        if not selected:
            return result
        points = self.client.points_by_payload_values(
            PAIR_EMBEDDING_COLLECTION,
            "canonical_topic",
            selected,
        )
        by_topic = {topic: [] for topic in selected}
        for point in points:
            topic = point.payload.get("canonical_topic")
            if topic in by_topic:
                by_topic[topic].append(point)
        for topic in selected:
            result[topic] = self._records_from_points(topic, by_topic[topic])
        return result

    def remove_topic(self, topic: str) -> None:
        self.client.delete_where(PAIR_EMBEDDING_COLLECTION, {"canonical_topic": topic})


class ClassPrototypeStore:
    """Persist compact per-role class centroids in PostgreSQL + pgvector."""

    def __init__(self, client=vector_store) -> None:
        self.client = client

    def replace_class(
        self,
        class_id: str,
        prototypes: tuple[ClassPairPrototype, ...],
        stream_context: tuple[float, ...] | None,
        profile_version: int,
    ) -> None:
        self.remove_class(class_id)
        for prototype in prototypes:
            for view, vector in prototype.centroids:
                identity = deterministic_vector_identity(
                    PAIR_PROTOTYPE_COLLECTION,
                    prototype.class_id,
                    prototype.identity.source,
                    prototype.identity.normalized_key,
                    prototype.identity.datatype,
                    view,
                )
                self.client.upsert(
                    PAIR_PROTOTYPE_COLLECTION,
                    identity,
                    list(vector),
                    {
                        "class_id": class_id,
                        "class_name": prototype.class_name,
                        "source": prototype.identity.source,
                        "normalized_key": prototype.identity.normalized_key,
                        "datatype": prototype.identity.datatype,
                        "representation_view": view,
                        "member_count": prototype.member_count,
                        "prototype_version": prototype.prototype_version,
                    },
                )
        if stream_context is not None:
            self.client.upsert(
                STREAM_CONTEXT_PROTOTYPE_COLLECTION,
                class_id,
                list(stream_context),
                {"class_id": class_id, "profile_version": profile_version},
            )

    def remove_class(self, class_id: str) -> None:
        self.client.delete_where(PAIR_PROTOTYPE_COLLECTION, {"class_id": class_id})
        self.client.delete(STREAM_CONTEXT_PROTOTYPE_COLLECTION, class_id)


class RecommendationMetadataStore:
    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def topic_state(self, topic: str) -> dict | None:
        return self.database.fetch_one(
            """
            SELECT canonical_topic, representation_version,
                   representation_fingerprint, representation_contract_version
            FROM topic_representations WHERE canonical_topic = %s
            """,
            (topic,),
        )

    def set_topic_state(self, topic: str, version: int, fingerprint: str) -> None:
        self.database.execute(
            """
            INSERT INTO topic_representations(
                canonical_topic, representation_version,
                representation_fingerprint, representation_contract_version
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (canonical_topic) DO UPDATE SET
                representation_version = EXCLUDED.representation_version,
                representation_fingerprint = EXCLUDED.representation_fingerprint,
                representation_contract_version = EXCLUDED.representation_contract_version,
                updated_at = now()
            """,
            (topic, version, fingerprint, REPRESENTATION_CONTRACT_VERSION),
        )

    def remove_topic_state(self, topic: str) -> None:
        self.database.execute(
            "DELETE FROM topic_representations WHERE canonical_topic = %s", (topic,)
        )

    def all_topic_states(self) -> list[dict]:
        return self.database.fetch_all(
            """
            SELECT canonical_topic, representation_version,
                   representation_fingerprint, representation_contract_version
            FROM topic_representations ORDER BY canonical_topic
            """
        )

    def is_suppressed(
        self, topic: str, class_id: str, topic_version: int, class_version: int
    ) -> bool:
        row = self.database.fetch_one(
            """
            SELECT 1 FROM class_recommendation_constraints
            WHERE canonical_topic = %s AND class_id = %s
              AND rejected_topic_version = %s
              AND rejected_class_profile_version = %s
            UNION ALL
            SELECT 1 FROM class_recommendation_dismissals
            WHERE canonical_topic = %s AND class_id = %s
              AND dismissed_topic_version = %s
              AND dismissed_class_profile_version = %s
            LIMIT 1
            """,
            (
                topic,
                class_id,
                topic_version,
                class_version,
                topic,
                class_id,
                topic_version,
                class_version,
            ),
        )
        return row is not None

    def reject(
        self, topic: str, class_id: str, topic_version: int, class_version: int
    ) -> None:
        self.database.execute(
            """
            INSERT INTO class_recommendation_constraints(
                canonical_topic, class_id, rejected_topic_version,
                rejected_class_profile_version
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (canonical_topic, class_id) DO UPDATE SET
                rejected_topic_version = EXCLUDED.rejected_topic_version,
                rejected_class_profile_version = EXCLUDED.rejected_class_profile_version,
                created_at = now()
            """,
            (topic, class_id, topic_version, class_version),
        )

    def dismiss(
        self, topic: str, class_id: str, topic_version: int, class_version: int
    ) -> None:
        self.database.execute(
            """
            INSERT INTO class_recommendation_dismissals(
                canonical_topic, class_id, dismissed_topic_version,
                dismissed_class_profile_version
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (canonical_topic, class_id) DO UPDATE SET
                dismissed_topic_version = EXCLUDED.dismissed_topic_version,
                dismissed_class_profile_version = EXCLUDED.dismissed_class_profile_version,
                created_at = now()
            """,
            (topic, class_id, topic_version, class_version),
        )

    def clear_suppression(self, topic: str, class_id: str) -> None:
        self.database.execute(
            "DELETE FROM class_recommendation_constraints WHERE canonical_topic = %s AND class_id = %s",
            (topic, class_id),
        )
        self.database.execute(
            "DELETE FROM class_recommendation_dismissals WHERE canonical_topic = %s AND class_id = %s",
            (topic, class_id),
        )

    def audit(self, *, action_type: str, details: dict) -> str:
        event_id = str(uuid.uuid4())
        recommendation = details.pop("recommendation", None)
        channel_scores = (
            asdict(recommendation.channel_scores) if recommendation else None
        )
        coverage = asdict(recommendation.coverage) if recommendation else None
        matched = (
            [
                {
                    "candidate": item.candidate.value,
                    "prototype": item.prototype_id,
                }
                for item in recommendation.matched_pairs
            ]
            if recommendation
            else None
        )
        self.database.execute(
            """
            INSERT INTO class_recommendation_actions(
                event_id, action_type, canonical_topic, original_topic,
                class_id, class_name, class_profile_version_before,
                class_profile_version_after, topic_representation_version,
                recommendation_id, recommendation_algorithm_version,
                overall_score, channel_scores, coverage, matched_pairs,
                duplicate_state, details
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb
            )
            """,
            (
                event_id,
                action_type,
                details.pop("canonical_topic", None),
                details.pop("original_topic", None),
                details.pop("class_id", None),
                details.pop("class_name", None),
                details.pop("class_profile_version_before", None),
                details.pop("class_profile_version_after", None),
                details.pop("topic_representation_version", None),
                recommendation.recommendation_id if recommendation else None,
                recommendation.algorithm_version if recommendation else None,
                recommendation.overall_score if recommendation else None,
                json.dumps(channel_scores),
                json.dumps(coverage),
                json.dumps(matched),
                details.pop("duplicate_state", None),
                json.dumps(details),
            ),
        )
        return event_id
