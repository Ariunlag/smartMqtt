"""Persistent system-candidate snapshots and immutable user feedback."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from services.database.postgres import postgres_client

logger = logging.getLogger(__name__)

TOPIC_FEEDBACK_ACTIONS = frozenset({"KEEP_TOPIC", "REMOVE_TOPIC"})
CANDIDATE_FEEDBACK_ACTIONS = frozenset({"ACCEPT_CANDIDATE", "DISMISS_CANDIDATE"})
FEEDBACK_ACTIONS = TOPIC_FEEDBACK_ACTIONS | CANDIDATE_FEEDBACK_ACTIONS


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def snapshot_fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


class RecommendedCandidateStore:
    """Version persistent candidate snapshots and record feedback against a snapshot."""

    def __init__(self, database=postgres_client) -> None:
        self.database = database

    def persist_snapshot(
        self,
        *,
        candidate_id: str,
        strategy_id: str,
        member_topics: tuple[str, ...],
        discovery_evidence: tuple[str, ...],
        evidence_snapshot: dict,
    ) -> int:
        fingerprint = snapshot_fingerprint(evidence_snapshot)
        member_json = _canonical_json(list(member_topics))
        discovery_json = _canonical_json(list(discovery_evidence))
        evidence_json = _canonical_json(evidence_snapshot)

        with self.database.transaction() as conn:
            current = conn.execute(
                """
                SELECT strategy_id, current_version
                FROM recommended_class_candidates
                WHERE candidate_id = %s
                FOR UPDATE
                """,
                (candidate_id,),
            ).fetchone()

            if current is None:
                version = 1
                conn.execute(
                    """
                    INSERT INTO recommended_class_candidates(
                        candidate_id, strategy_id, current_version
                    ) VALUES (%s, %s, %s)
                    """,
                    (candidate_id, strategy_id, version),
                )
                self._insert_version(
                    conn,
                    candidate_id=candidate_id,
                    candidate_version=version,
                    member_json=member_json,
                    discovery_json=discovery_json,
                    evidence_json=evidence_json,
                    fingerprint=fingerprint,
                )
                return version

            if current["strategy_id"] != strategy_id:
                raise ValueError("Persistent candidate strategy cannot change")

            version = int(current["current_version"])
            current_snapshot = conn.execute(
                """
                SELECT snapshot_fingerprint
                FROM recommended_class_candidate_versions
                WHERE candidate_id = %s AND candidate_version = %s
                """,
                (candidate_id, version),
            ).fetchone()
            if current_snapshot and current_snapshot["snapshot_fingerprint"] == fingerprint:
                conn.execute(
                    """
                    UPDATE recommended_class_candidates
                    SET last_seen_at = now(), updated_at = now()
                    WHERE candidate_id = %s
                    """,
                    (candidate_id,),
                )
                return version

            version += 1
            self._insert_version(
                conn,
                candidate_id=candidate_id,
                candidate_version=version,
                member_json=member_json,
                discovery_json=discovery_json,
                evidence_json=evidence_json,
                fingerprint=fingerprint,
            )
            conn.execute(
                """
                UPDATE recommended_class_candidates
                SET current_version = %s, last_seen_at = now(), updated_at = now()
                WHERE candidate_id = %s
                """,
                (version, candidate_id),
            )
            return version

    @staticmethod
    def _insert_version(
        conn,
        *,
        candidate_id: str,
        candidate_version: int,
        member_json: str,
        discovery_json: str,
        evidence_json: str,
        fingerprint: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO recommended_class_candidate_versions(
                candidate_id, candidate_version, member_topics,
                discovery_evidence, evidence_snapshot, snapshot_fingerprint
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            """,
            (
                candidate_id,
                candidate_version,
                member_json,
                discovery_json,
                evidence_json,
                fingerprint,
            ),
        )

    def get_snapshot(self, candidate_id: str, candidate_version: int) -> dict | None:
        return self.database.fetch_one(
            """
            SELECT c.candidate_id, c.strategy_id, v.candidate_version,
                   v.member_topics, v.discovery_evidence,
                   v.evidence_snapshot, v.snapshot_fingerprint, v.created_at
            FROM recommended_class_candidates c
            JOIN recommended_class_candidate_versions v
              ON v.candidate_id = c.candidate_id
            WHERE c.candidate_id = %s AND v.candidate_version = %s
            """,
            (candidate_id, candidate_version),
        )

    def latest_shadow_observation(
        self,
        candidate_id: str,
        candidate_version: int,
    ) -> dict | None:
        """Return the latest recorded shadow exposure without making feedback depend on it."""
        try:
            return self.database.fetch_one(
                """
                SELECT observation_id::text AS observation_id, shadow_run_id::text AS shadow_run_id,
                       membership_model_id::text AS membership_model_id,
                       candidate_quality_model_id::text AS candidate_quality_model_id,
                       created_at
                FROM recommendation_shadow_observations
                WHERE candidate_id = %s AND candidate_version = %s
                ORDER BY created_at DESC, observation_id DESC
                LIMIT 1
                """,
                (candidate_id, candidate_version),
            )
        except Exception:
            logger.exception("Could not resolve recommendation shadow provenance")
            return None

    def latest_live_observation(
        self,
        candidate_id: str,
        candidate_version: int,
    ) -> dict | None:
        """Return the latest live exposure; absence must never block feedback writes."""
        try:
            return self.database.fetch_one(
                """
                SELECT observation_id::text AS observation_id,
                       live_run_id::text AS live_run_id,
                       model_id::text AS model_id, baseline_rank, live_rank, created_at
                FROM recommendation_live_observations
                WHERE candidate_id = %s AND candidate_version = %s
                ORDER BY created_at DESC, observation_id DESC
                LIMIT 1
                """,
                (candidate_id, candidate_version),
            )
        except Exception:
            logger.exception("Could not resolve recommendation live provenance")
            return None

    def record_feedback(
        self,
        *,
        candidate_id: str,
        candidate_version: int,
        action_type: str,
        topic: str | None = None,
    ) -> dict:
        if action_type not in FEEDBACK_ACTIONS:
            raise ValueError(f"Unknown recommendation feedback action: {action_type}")
        if action_type in TOPIC_FEEDBACK_ACTIONS and not topic:
            raise ValueError(f"{action_type} requires a topic")
        if action_type in CANDIDATE_FEEDBACK_ACTIONS and topic is not None:
            raise ValueError(f"{action_type} does not accept a topic")

        snapshot = self.get_snapshot(candidate_id, candidate_version)
        if snapshot is None:
            raise LookupError("Recommended candidate snapshot was not found")

        members = tuple(snapshot["member_topics"])
        if action_type in TOPIC_FEEDBACK_ACTIONS and topic not in members:
            raise ValueError("Topic feedback must reference a member of this candidate version")

        shadow = self.latest_shadow_observation(candidate_id, candidate_version)
        shadow_observation_id = str(shadow["observation_id"]) if shadow else None
        live = self.latest_live_observation(candidate_id, candidate_version)
        live_observation_id = str(live["observation_id"]) if live else None
        evidence_snapshot = {
            "candidate_id": str(snapshot["candidate_id"]),
            "candidate_version": int(snapshot["candidate_version"]),
            "strategy_id": snapshot["strategy_id"],
            "member_topics": list(members),
            "discovery_evidence": list(snapshot["discovery_evidence"]),
            "snapshot_fingerprint": snapshot["snapshot_fingerprint"],
            "candidate_evidence": snapshot["evidence_snapshot"],
            "shadow_observation_id": shadow_observation_id,
            "live_observation_id": live_observation_id,
        }
        feedback_id = str(uuid.uuid4())
        self.database.execute(
            """
            INSERT INTO recommended_class_feedback(
                feedback_id, candidate_id, candidate_version,
                action_type, topic, evidence_snapshot,
                shadow_observation_id, live_observation_id
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                feedback_id,
                candidate_id,
                candidate_version,
                action_type,
                topic,
                _canonical_json(evidence_snapshot),
                shadow_observation_id,
                live_observation_id,
            ),
        )
        return {
            "feedback_id": feedback_id,
            "candidate_id": candidate_id,
            "candidate_version": candidate_version,
            "action_type": action_type,
            "topic": topic,
            "shadow_observation_id": shadow_observation_id,
            "live_observation_id": live_observation_id,
        }


recommended_candidate_store = RecommendedCandidateStore()
