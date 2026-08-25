"""Production composition root for pair-level class recommendation."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import replace
from threading import RLock

from models.mqtt_message import MQTTMessage
from services.class_manager import ClassManager
from services.store.canonical_identity_store import CanonicalIdentityStore
from services.store.embedding_store import TopicEmbeddingStore
from services.store.relation_store import ClassStore, DupeStore

from .domain import ClassPairPrototype, ClassProfile, TopicRecommendations
from .embedding import PairEmbedder
from .matching import PairClassMatcher, centroid
from .profiling import StreamProfiler
from .representations import PairRepresentationBuilder
from .stores import (
    ClassPrototypeStore,
    PairEmbeddingStore,
    RecommendationMetadataStore,
)
from .temporal import TemporalChangeType, TemporalStreamProfiler

logger = logging.getLogger(__name__)


class StaleRecommendationError(ValueError):
    """A human action referenced evidence that has since changed."""


class ClassRecommendationApplication:
    """Own recommendation processing, derived profiles, actions, and locks."""

    def __init__(
        self,
        *,
        model,
        class_store: ClassStore,
        identity_store: CanonicalIdentityStore,
        topic_embedding_store: TopicEmbeddingStore,
        dupe_store: DupeStore,
        pair_store: PairEmbeddingStore,
        prototype_store: ClassPrototypeStore,
        metadata_store: RecommendationMetadataStore,
        stream_context_refresher=None,
        processing_capacity: int = 1000,
    ) -> None:
        self.class_store = class_store
        self.class_manager = ClassManager(class_store)
        self.identity_store = identity_store
        self.topic_embedding_store = topic_embedding_store
        self.dupe_store = dupe_store
        self.pair_store = pair_store
        self.prototype_store = prototype_store
        self.metadata_store = metadata_store
        self.stream_context_refresher = stream_context_refresher
        self.profiler = StreamProfiler()
        self.temporal_profiler = TemporalStreamProfiler()
        self.builder = PairRepresentationBuilder()
        self.embedder = PairEmbedder(model)
        self.matcher = PairClassMatcher()
        self._topic_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._profile_lock = RLock()
        self._action_lock = RLock()
        self._profiles: dict[str, ClassProfile] = {}
        self._temporal_profiles = {}
        self._materialized_topics: set[str] = set()
        self._cache: dict[tuple[str, int, str, int, str], object] = {}
        from .processing import ClassRecommendationProcessingService

        self.processing_service = ClassRecommendationProcessingService(
            self, capacity=processing_capacity
        )

    async def observe(self, message: MQTTMessage) -> bool:
        """Refresh one canonical topic only when its pair contract changed."""
        canonical = await asyncio.to_thread(
            self.identity_store.resolve_canonical, message.topic
        )
        if canonical != message.topic:
            return False
        async with self._topic_locks[canonical]:
            profile = self.profiler.profile(canonical, message.tags, message.fields)
            fingerprint = self.builder.fingerprint(profile)
            previous = await asyncio.to_thread(
                self.metadata_store.topic_state, canonical
            )
            pair_material_exists = canonical in self._materialized_topics
            if previous is not None and not pair_material_exists:
                stored_pairs = await asyncio.to_thread(
                    self.pair_store.get_topic, canonical
                )
                pair_material_exists = bool(stored_pairs)
                if pair_material_exists:
                    self._materialized_topics.add(canonical)
            temporal = self.temporal_profiler.update(
                self._temporal_profiles.get(canonical), profile
            )
            self._temporal_profiles[canonical] = temporal.profile
            relevant_changes = {
                TemporalChangeType.KEY_ADDED,
                TemporalChangeType.KEY_MISSING,
                TemporalChangeType.KEY_REAPPEARED,
                TemporalChangeType.TYPE_CHANGED,
                TemporalChangeType.STABLE_VALUE_CHANGED,
            }
            changed = any(
                item.change_type in relevant_changes for item in temporal.changes
            )
            stable_established_against_changed_storage = (
                previous is not None
                and previous["representation_fingerprint"] != fingerprint
                and any(
                    item.change_type is TemporalChangeType.STABLE_VALUE_ESTABLISHED
                    for item in temporal.changes
                )
            )
            if (
                previous
                and pair_material_exists
                and (
                    previous["representation_fingerprint"] == fingerprint
                    or not (changed or stable_established_against_changed_storage)
                )
            ):
                return False
            version = int(previous["representation_version"]) + 1 if previous else 1
            representations = self.builder.build(
                profile,
                canonical_topic=canonical,
                original_topic=message.topic,
                representation_version=version,
            )
            embeddings = await asyncio.to_thread(self.embedder.embed, representations)
            stored_stream = None
            if self.stream_context_refresher is not None and previous is not None:
                stored_stream = await asyncio.to_thread(
                    self.topic_embedding_store.get, canonical
                )
            if (
                self.stream_context_refresher is not None
                and previous is not None
                and (
                    stored_stream is None
                    or stored_stream.get("tags", {}) != dict(message.tags)
                )
            ):
                # This refreshes the one authoritative duplicate stream vector;
                # it does not create a recommendation-specific copy.
                await self.stream_context_refresher(canonical, message.tags)
            await asyncio.to_thread(
                self.pair_store.replace_topic, canonical, embeddings
            )
            self._materialized_topics.add(canonical)
            await asyncio.to_thread(
                self.metadata_store.set_topic_state, canonical, version, fingerprint
            )
            affected = await asyncio.to_thread(
                self.class_store.classes_for_topic, canonical
            )
            for class_record in affected:
                class_record = dict(class_record)
                class_record["profile_version"] = await asyncio.to_thread(
                    self.class_store.bump_profile_version, class_record["name"]
                )
                await asyncio.to_thread(self.rebuild_profile, class_record)
            self._invalidate_topic(canonical)
            return True

    def warm_profiles(self) -> None:
        for class_record in self.class_store.get_all():
            self.rebuild_profile(class_record)

    def rebuild_profile(self, class_record: dict) -> ClassProfile:
        """Exactly rebuild one class from authoritative membership and vectors."""
        grouped: dict[object, list] = defaultdict(list)
        stream_vectors = []
        for topic in class_record["topics"]:
            canonical = self.identity_store.resolve_canonical(topic)
            for record in self.pair_store.get_topic(canonical):
                grouped[record.representation.identity].append(record)
            stream = self.topic_embedding_store.get(canonical)
            if stream is not None:
                stream_vectors.append(stream["embedding"])
        prototypes = []
        for identity in sorted(grouped):
            members = grouped[identity]
            view_centroids = []
            for view in ("key", "value", "key_value", "schema", "numeric_key"):
                vectors = [
                    vector
                    for member in members
                    if (vector := member.vector_for(view)) is not None
                ]
                if vectors:
                    view_centroids.append((view, centroid(vectors)))
            prototypes.append(
                ClassPairPrototype(
                    class_id=class_record["class_id"],
                    class_name=class_record["name"],
                    identity=identity,
                    centroids=tuple(view_centroids),
                    member_count=len(members),
                    prototype_version=int(class_record["profile_version"]),
                )
            )
        stream_centroid = centroid(stream_vectors) if stream_vectors else None
        profile = ClassProfile(
            class_id=class_record["class_id"],
            class_name=class_record["name"],
            profile_version=int(class_record["profile_version"]),
            pair_prototypes=tuple(prototypes),
            stream_context_centroid=stream_centroid,
        )
        self.prototype_store.replace_class(
            profile.class_id,
            profile.pair_prototypes,
            profile.stream_context_centroid,
            profile.profile_version,
        )
        with self._profile_lock:
            self._profiles[profile.class_id] = profile
            self._invalidate_class(profile.class_id)
        return profile

    def recommendations_for_topic(self, topic: str) -> TopicRecommendations:
        canonical = self.identity_store.resolve_canonical(topic)
        if canonical != topic and self.identity_store.is_duplicate_alias(topic):
            return TopicRecommendations(canonical, topic, 0, ())
        state = self.metadata_store.topic_state(canonical)
        if state is None:
            return TopicRecommendations(canonical, topic, 0, ())
        topic_version = int(state["representation_version"])
        pairs = self.pair_store.get_topic(canonical)
        stream = self.topic_embedding_store.get(canonical)
        stream_vector = tuple(stream["embedding"]) if stream else None
        duplicate_pending = self.dupe_store.has_pending(canonical)
        with self._profile_lock:
            profiles = tuple(self._profiles.values())
        if not profiles:
            self.warm_profiles()
            with self._profile_lock:
                profiles = tuple(self._profiles.values())
        results = []
        for profile in sorted(profiles, key=lambda item: item.class_id):
            if not profile.pair_prototypes and profile.stream_context_centroid is None:
                continue
            if self.metadata_store.is_suppressed(
                canonical, profile.class_id, topic_version, profile.profile_version
            ):
                continue
            key = (
                canonical,
                topic_version,
                profile.class_id,
                profile.profile_version,
                "pair-greedy-equal-mean-v1",
            )
            recommendation = self._cache.get(key)
            if recommendation is None:
                recommendation = self.matcher.recommend(
                    canonical_topic=canonical,
                    original_topic=topic,
                    topic_version=topic_version,
                    pairs=pairs,
                    stream_context=stream_vector,
                    profile=profile,
                    duplicate_pending=duplicate_pending,
                )
                self._cache[key] = recommendation
            results.append(recommendation)
        results.sort(key=lambda item: (-item.overall_score, item.class_id))
        ranked = tuple(
            replace(item, rank=index) for index, item in enumerate(results, 1)
        )
        return TopicRecommendations(canonical, topic, topic_version, ranked)

    def recommendations_for_class(self, class_name: str) -> tuple:
        class_record = self.class_store.get(class_name)
        if class_record is None:
            raise ValueError(f"Class '{class_name}' not found")
        rows = []
        member_topics = set(class_record["topics"])
        for state in self._all_topic_states():
            topic = state["canonical_topic"]
            if topic in member_topics or self.identity_store.is_duplicate_alias(topic):
                continue
            recommendation = next(
                (
                    item
                    for item in self.recommendations_for_topic(topic).recommendations
                    if item.class_id == class_record["class_id"]
                ),
                None,
            )
            if recommendation is not None:
                rows.append(recommendation)
        rows.sort(key=lambda item: (-item.overall_score, item.canonical_topic))
        return tuple(replace(item, rank=index) for index, item in enumerate(rows, 1))

    def _all_topic_states(self):
        return self.metadata_store.all_topic_states()

    def apply_action(
        self,
        *,
        action: str,
        class_name: str,
        topic: str,
        topic_version: int | None = None,
        class_profile_version: int | None = None,
        recommendation_id: str | None = None,
    ) -> dict:
        with self._action_lock:
            return self._apply_action_locked(
                action=action,
                class_name=class_name,
                topic=topic,
                topic_version=topic_version,
                class_profile_version=class_profile_version,
                recommendation_id=recommendation_id,
            )

    def _apply_action_locked(
        self,
        *,
        action: str,
        class_name: str,
        topic: str,
        topic_version: int | None,
        class_profile_version: int | None,
        recommendation_id: str | None,
    ) -> dict:
        canonical = self.identity_store.resolve_canonical(topic)
        if canonical != topic and self.identity_store.is_duplicate_alias(topic):
            raise ValueError(f"Topic '{topic}' is an alias of '{canonical}'")
        class_record = self.class_store.get(class_name)
        if class_record is None:
            raise ValueError(f"Class '{class_name}' not found")
        state = self.metadata_store.topic_state(canonical)
        current_topic_version = int(state["representation_version"]) if state else 0
        current_class_version = int(class_record["profile_version"])
        recommendation = next(
            (
                row
                for row in self.recommendations_for_topic(canonical).recommendations
                if row.class_id == class_record["class_id"]
            ),
            None,
        )
        if action.startswith("RECOMMENDATION_") and (
            topic_version != current_topic_version
            or class_profile_version != current_class_version
            or recommendation is None
            or recommendation.recommendation_id != recommendation_id
        ):
            raise StaleRecommendationError(
                "Recommendation evidence is stale; refresh before applying the action"
            )
        before = current_class_version
        after = before
        topics = list(class_record["topics"])
        if action in {"RECOMMENDATION_ACCEPT", "MANUAL_ADD"}:
            if canonical not in topics:
                topics.append(canonical)
                class_record = self.class_store.update(class_name, topics)
                after = int(class_record["profile_version"])
                self.rebuild_profile(class_record)
            self.metadata_store.clear_suppression(canonical, class_record["class_id"])
        elif action == "MANUAL_REMOVE":
            if canonical in topics:
                class_record = self.class_store.update(
                    class_name, [item for item in topics if item != canonical]
                )
                after = int(class_record["profile_version"])
                self.rebuild_profile(class_record)
        elif action == "RECOMMENDATION_REJECT":
            self.metadata_store.reject(
                canonical, class_record["class_id"], current_topic_version, before
            )
        elif action == "RECOMMENDATION_DISMISS":
            self.metadata_store.dismiss(
                canonical, class_record["class_id"], current_topic_version, before
            )
        else:
            raise ValueError(f"Unsupported class action: {action}")
        event_id = self.metadata_store.audit(
            action_type=action,
            details={
                "canonical_topic": canonical,
                "original_topic": topic,
                "class_id": class_record["class_id"],
                "class_name": class_name,
                "class_profile_version_before": before,
                "class_profile_version_after": after,
                "topic_representation_version": current_topic_version,
                "duplicate_state": (
                    "PENDING" if self.dupe_store.has_pending(canonical) else "ACTIVE"
                ),
                "recommendation": recommendation,
            },
        )
        return {
            "event_id": event_id,
            "action_type": action,
            "canonical_topic": canonical,
            "class_id": class_record["class_id"],
            "class_name": class_name,
            "class_profile_version": after,
        }

    def class_created(self, record: dict) -> None:
        self.rebuild_profile(record)
        self.metadata_store.audit(
            action_type="CLASS_CREATE",
            details={
                "class_id": record["class_id"],
                "class_name": record["name"],
                "class_profile_version_after": record["profile_version"],
            },
        )

    def create_class(self, name: str, topics: list[str]) -> dict:
        with self._action_lock:
            record = self.class_manager.create_class(name, topics)
            self.class_created(record)
            return record

    def update_class(self, name: str, topics: list[str]) -> dict | None:
        with self._action_lock:
            previous = self.class_manager.get_class(name)
            record = self.class_manager.update_class(name, topics)
            if record is None:
                return None
            self.class_updated(record)
            previous_topics = set(previous["topics"]) if previous else set()
            current_topics = set(record["topics"])
            for action, changed_topics in (
                ("MANUAL_ADD", current_topics - previous_topics),
                ("MANUAL_REMOVE", previous_topics - current_topics),
            ):
                for topic in sorted(changed_topics):
                    self.metadata_store.audit(
                        action_type=action,
                        details={
                            "canonical_topic": topic,
                            "original_topic": topic,
                            "class_id": record["class_id"],
                            "class_name": name,
                            "class_profile_version_before": previous["profile_version"],
                            "class_profile_version_after": record["profile_version"],
                        },
                    )
            return record

    def delete_class(self, name: str) -> bool:
        with self._action_lock:
            existing = self.class_manager.get_class(name)
            if existing is None:
                raise ValueError(f"Class '{name}' not found")
            self.class_manager.delete_class(name)
            self.class_deleted(existing)
            return True

    def class_updated(self, record: dict) -> None:
        self.rebuild_profile(record)

    def class_deleted(self, record: dict) -> None:
        self.prototype_store.remove_class(record["class_id"])
        with self._profile_lock:
            self._profiles.pop(record["class_id"], None)
            self._invalidate_class(record["class_id"])
        self.metadata_store.audit(
            action_type="CLASS_DELETE",
            details={
                "class_id": record["class_id"],
                "class_name": record["name"],
                "class_profile_version_before": record["profile_version"],
            },
        )

    def canonicalized(self, canonical: str, aliases: tuple[str, ...]) -> None:
        for alias in aliases:
            self.pair_store.remove_topic(alias)
            self.metadata_store.remove_topic_state(alias)
            self._invalidate_topic(alias)
        for class_record in self.class_store.classes_for_topic(canonical):
            class_record = dict(class_record)
            class_record["profile_version"] = self.class_store.bump_profile_version(
                class_record["name"]
            )
            self.rebuild_profile(class_record)

    def _invalidate_topic(self, topic: str) -> None:
        with self._profile_lock:
            self._cache = {
                key: value for key, value in self._cache.items() if key[0] != topic
            }

    def _invalidate_class(self, class_id: str) -> None:
        self._cache = {
            key: value for key, value in self._cache.items() if key[2] != class_id
        }


def build_class_recommendation_application(
    *,
    model,
    class_store=None,
    identity_store=None,
    topic_embedding_store=None,
    dupe_store=None,
    pair_store=None,
    prototype_store=None,
    metadata_store=None,
    stream_context_refresher=None,
    processing_capacity: int = 1000,
) -> ClassRecommendationApplication:
    from services.store.canonical_identity_store import canonical_identity_store
    from services.store.embedding_store import (
        topic_embedding_store as default_topic_store,
    )
    from services.store.relation_store import class_store as default_class_store
    from services.store.relation_store import dupe_store as default_dupe_store

    return ClassRecommendationApplication(
        model=model,
        class_store=class_store or default_class_store,
        identity_store=identity_store or canonical_identity_store,
        topic_embedding_store=topic_embedding_store or default_topic_store,
        dupe_store=dupe_store or default_dupe_store,
        pair_store=pair_store or PairEmbeddingStore(),
        prototype_store=prototype_store or ClassPrototypeStore(),
        metadata_store=metadata_store or RecommendationMetadataStore(),
        stream_context_refresher=stream_context_refresher,
        processing_capacity=processing_capacity,
    )
