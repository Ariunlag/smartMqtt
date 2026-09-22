"""Recommendation APIs.

The legacy Saved-Class recommendation endpoints remain available through
``api/classes.py`` for compatibility, but this router exposes the system-derived
recommended-class workflow used by the dashboard.
"""

import asyncio
import logging
from dataclasses import asdict
from uuid import UUID

from config import config
from fastapi import APIRouter, HTTPException, Request
from models.api_models import RecommendedClassFeedbackRequest, AdaptiveGroupActionRequest
from services.class_recommendation.adaptive import RevisionConflict
from services.class_recommendation.candidate_feedback import recommended_candidate_store
from services.class_recommendation.discovery import (
    RecommendedClassDiscovery,
    RecommendedClassDiscoveryConfig,
    TopicEvidenceMatcher,
)
from services.class_recommendation.live_ranking import recommendation_live_ranker
from services.class_recommendation.shadow import recommendation_shadow_scorer
from services.class_recommendation.strategies import (
    DEFAULT_STRATEGY_ID,
    TagValueCentroidStrategyConfig,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Class Recommendations"])


def adaptive_service(request: Request):
    service = getattr(request.app.state.class_recommendation, "adaptive", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Adaptive recommendation service is not configured")
    return service


@router.get("/adaptive-recommendations")
async def adaptive_recommendations(request: Request):
    return await asyncio.to_thread(adaptive_service(request).recommendations)


@router.post("/adaptive-recommendations/{group_id}/actions")
async def adaptive_group_action(group_id: str, payload: AdaptiveGroupActionRequest, request: Request):
    try:
        return await asyncio.to_thread(adaptive_service(request).edit, group_id, payload.action,
                                       payload.revision, topic=payload.topic, name=payload.name)
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class _FilteredRecommendationMetadata:
    """User-facing metadata view that hides configured synthetic topic namespaces."""

    def __init__(self, store, excluded_prefixes: tuple[str, ...]) -> None:
        self.store = store
        self.excluded_prefixes = tuple(excluded_prefixes)

    def all_topic_states(self):
        return [
            row
            for row in self.store.all_topic_states()
            if not self._excluded(str(row["canonical_topic"]))
        ]

    def topic_state(self, topic):
        if self._excluded(str(topic)):
            return None
        return self.store.topic_state(topic)

    def _excluded(self, topic: str) -> bool:
        return any(topic.startswith(prefix) for prefix in self.excluded_prefixes)


@router.get("/topics/{topic:path}/class-recommendations")
async def topic_class_recommendations(topic: str, request: Request):
    """Legacy topic -> Saved Class view kept for API compatibility."""
    result = request.app.state.class_recommendation.recommendations_for_topic(topic)
    return asdict(result)


@router.get("/recommended-classes")
async def recommended_class_candidates(
    request: Request,
    strategy: str = DEFAULT_STRATEGY_ID,
):
    """Return generated candidates with shadow diagnostics and optional live reordering."""
    application = request.app.state.class_recommendation
    metadata_store = _FilteredRecommendationMetadata(
        application.metadata_store,
        config.SYSTEM_RECOMMENDATION_EXCLUDED_TOPIC_PREFIXES,
    )
    discovery = RecommendedClassDiscovery(
        metadata_store=metadata_store,
        pair_store=application.pair_store,
        topic_embedding_store=application.topic_embedding_store,
        identity_store=application.identity_store,
        dupe_store=application.dupe_store,
        config=RecommendedClassDiscoveryConfig(
            min_cluster_size=config.SYSTEM_RECOMMENDATION_MIN_CLUSTER_SIZE,
            min_samples=config.SYSTEM_RECOMMENDATION_MIN_SAMPLES,
            allow_single_cluster=config.SYSTEM_RECOMMENDATION_ALLOW_SINGLE_CLUSTER,
        ),
        centroid_config=TagValueCentroidStrategyConfig(
            threshold=config.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_THRESHOLD,
            min_topic_count=config.SYSTEM_RECOMMENDATION_TAG_VALUE_CENTROID_MIN_TOPICS,
        ),
        strategy_id=strategy,
        candidate_store=recommended_candidate_store,
    )
    try:
        baseline = await asyncio.to_thread(discovery.discover)
    except ValueError as exc:
        if "Unknown recommendation strategy" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise

    try:
        shadow_evaluation = await asyncio.to_thread(
            recommendation_shadow_scorer.evaluate,
            baseline,
        )
    except Exception:  # shadow evaluation must never affect recommendation availability
        logger.exception("Recommendation shadow evaluation failed")
        shadow_evaluation = {
            "mode": "shadow",
            "status": "error",
            "reason": "shadow_evaluation_failed",
            "ranking_effect": "none",
            "baseline_order_preserved": True,
            "models": {},
            "candidates": [],
        }

    try:
        result, live_ranking = await asyncio.to_thread(
            recommendation_live_ranker.apply,
            baseline,
        )
    except Exception:  # live ranking must fail closed to the baseline order
        logger.exception("Recommendation live ranking failed")
        result = baseline
        live_ranking = {
            "mode": "live",
            "status": "fallback",
            "reason": "live_ranking_failed",
            "ranking_effect": "baseline_fallback",
            "membership_effect": "none",
            "model": None,
        }

    payload = asdict(result)
    payload["shadow_evaluation"] = shadow_evaluation
    payload["live_ranking"] = live_ranking
    return payload


def _stream_vector(row):
    if row is None or row.get("embedding") is None:
        return None
    return tuple(float(value) for value in row["embedding"])


def _feedback_topic_evidence(
    request: Request,
    candidate_id: str,
    candidate_version: int,
    topic: str,
):
    """Resolve exact server-side evidence for a topic feedback action.

    Candidate snapshots intentionally contain only discovered members. When a user
    adds an outside topic, or edits the anchor whose self-comparison is absent, we
    compute the same pair/stream comparison at action time and persist it only with
    that immutable feedback event.
    """
    snapshot = recommended_candidate_store.get_snapshot(candidate_id, candidate_version)
    if snapshot is None:
        raise LookupError("Recommended candidate snapshot was not found")

    application = request.app.state.class_recommendation
    canonical_topic = application.identity_store.resolve_canonical(topic)
    candidate_snapshot = snapshot.get("evidence_snapshot") or {}
    existing = next(
        (
            item
            for item in candidate_snapshot.get("topic_evidence", ())
            if item.get("topic") == canonical_topic
        ),
        None,
    )
    if existing is not None:
        return canonical_topic, None

    members = tuple(str(member) for member in snapshot.get("member_topics") or ())
    anchor = str(candidate_snapshot.get("anchor_topic") or (members[0] if members else ""))
    if not anchor:
        raise ValueError("Candidate has no reference topic for feedback evidence")

    reference_topic = anchor
    if canonical_topic == anchor:
        reference_topic = next((member for member in members if member != anchor), "")
    if not reference_topic:
        raise ValueError("At least two topics are required to score membership feedback")

    candidate_pairs = tuple(application.pair_store.get_topic(canonical_topic))
    reference_pairs = tuple(application.pair_store.get_topic(reference_topic))
    candidate_stream = _stream_vector(application.topic_embedding_store.get(canonical_topic))
    reference_stream = _stream_vector(application.topic_embedding_store.get(reference_topic))
    if not candidate_pairs and candidate_stream is None:
        raise ValueError("Topic evidence is not available yet")

    duplicate_pending = (
        application.dupe_store.has_pending(canonical_topic)
        if hasattr(application.dupe_store, "has_pending")
        else False
    )
    evidence = TopicEvidenceMatcher.compare(
        candidate_topic=canonical_topic,
        candidate_pairs=candidate_pairs,
        candidate_stream=candidate_stream,
        reference_topic=reference_topic,
        reference_pairs=reference_pairs,
        reference_stream=reference_stream,
        duplicate_pending=duplicate_pending,
    )
    return canonical_topic, asdict(evidence)


@router.post("/recommended-classes/{candidate_id}/feedback")
async def recommended_class_feedback(
    candidate_id: UUID,
    payload: RecommendedClassFeedbackRequest,
    request: Request,
):
    """Record an immutable label against an exact persistent candidate version."""
    try:
        feedback_topic = payload.topic
        topic_evidence = None
        if payload.topic is not None:
            feedback_topic, topic_evidence = await asyncio.to_thread(
                _feedback_topic_evidence,
                request,
                str(candidate_id),
                payload.candidate_version,
                payload.topic,
            )
        return await asyncio.to_thread(
            recommended_candidate_store.record_feedback,
            candidate_id=str(candidate_id),
            candidate_version=payload.candidate_version,
            action_type=payload.action,
            topic=feedback_topic,
            shadow_run_id=(
                str(payload.shadow_run_id) if payload.shadow_run_id is not None else None
            ),
            live_run_id=(
                str(payload.live_run_id) if payload.live_run_id is not None else None
            ),
            topic_evidence=topic_evidence,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/class-recommendations/status")
async def class_recommendation_status(request: Request):
    return request.app.state.class_recommendation_processing.status()
