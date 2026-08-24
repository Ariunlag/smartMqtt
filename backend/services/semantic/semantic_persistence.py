"""Explicit JSON serialization and repositories for semantic application state."""

from __future__ import annotations

import copy
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from numbers import Real
from threading import RLock
from typing import Any

from psycopg.types.json import Jsonb

from .candidate_confirmation import CandidateIdentity
from .confirmed_membership import ConfirmedSemanticMembership
from .known_class_registry import SemanticClassDefinition
from .multi_view_consensus import (
    MultiViewConsensusResult,
    RepresentationClassConsensus,
    RepresentationViewWinner,
)
from .representation_class_scoring import (
    RepresentationClassCentroids,
    RepresentationClassEvidence,
    RepresentationClassEvidenceMatrix,
    RepresentationClassScores,
)
from .representation_embedder import RepresentationEmbeddings
from .representations import StreamRepresentations
from .semantic_class_decision import (
    SemanticClassDecision,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
)
from .semantic_feedback_workflow import NegativeMembershipConstraint
from .semantic_review_runtime import PendingSemanticCandidate
from .semantic_runtime import SemanticRuntimeTopicState
from .semantic_state import (
    SEMANTIC_REPRESENTATION_CONTRACT_VERSION,
    SEMANTIC_STATE_SCHEMA_VERSION,
    SemanticApplicationSnapshot,
    SemanticPersistenceMetadata,
)
from .temporal_profile import TemporalEntryState, TemporalStreamProfile
from .trusted_class_evidence import TrustedClassEvidence
from .unknown_stream_pool import UnknownStreamEntry, UnknownStreamPoolSnapshot

REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)

_DATACLASS_TYPES = {
    cls.__name__: cls
    for cls in (
        TemporalEntryState,
        TemporalStreamProfile,
        StreamRepresentations,
        RepresentationEmbeddings,
        RepresentationClassScores,
        RepresentationClassEvidence,
        RepresentationClassEvidenceMatrix,
        RepresentationViewWinner,
        RepresentationClassConsensus,
        MultiViewConsensusResult,
        SemanticClassDecision,
        SemanticRuntimeTopicState,
        UnknownStreamEntry,
        UnknownStreamPoolSnapshot,
        TrustedClassEvidence,
        NegativeMembershipConstraint,
        RepresentationClassCentroids,
        SemanticClassDefinition,
        CandidateIdentity,
        PendingSemanticCandidate,
        ConfirmedSemanticMembership,
    )
}
_ENUM_TYPES = {
    cls.__name__: cls
    for cls in (SemanticClassDecisionState, SemanticClassDecisionReason)
}


class SemanticSnapshotValidationError(ValueError):
    """Raised before malformed persisted state can reach live stores."""


class SemanticPersistenceCompatibilityError(SemanticSnapshotValidationError):
    """Raised when persisted vectors do not match the active contract."""


@dataclass(frozen=True, slots=True)
class SemanticPersistenceRecord:
    """One repository row with separately queryable compatibility metadata."""

    state_key: str
    schema_version: int
    generation: int
    model_fingerprint: str
    representation_contract_version: str
    policy_config: dict[str, Any]
    payload: dict[str, Any]
    updated_at: datetime


class SemanticSnapshotSerializer:
    """Serialize only a fixed whitelist of semantic state value objects."""

    def serialize(
        self, snapshot: SemanticApplicationSnapshot, state_key: str = "default"
    ) -> SemanticPersistenceRecord:
        self.validate(snapshot)
        metadata = snapshot.metadata
        return SemanticPersistenceRecord(
            state_key=_required_text(state_key, "state_key"),
            schema_version=metadata.schema_version,
            generation=snapshot.generation,
            model_fingerprint=metadata.model_fingerprint,
            representation_contract_version=metadata.representation_contract_version,
            policy_config=_plain_json(dict(metadata.policy_config), "policy_config"),
            payload={
                "runtime_states": self._encode(snapshot.runtime_states),
                "semantic_context_generation": snapshot.semantic_context_generation,
                "unknown_pool": self._encode(snapshot.unknown_pool),
                "trusted_evidence": self._encode(snapshot.trusted_evidence),
                "constraints": self._encode(snapshot.constraints),
                "confirmed_memberships": self._encode(snapshot.confirmed_memberships),
                "known_classes": self._encode(snapshot.known_classes),
                "class_catalog": self._encode(snapshot.class_catalog),
                "pending_candidates": self._encode(snapshot.pending_candidates),
                "suppressed_candidates": self._encode(snapshot.suppressed_candidates),
            },
            updated_at=datetime.now(timezone.utc),
        )

    def deserialize(
        self,
        record: SemanticPersistenceRecord,
        *,
        expected_model_fingerprint: str,
        expected_representation_contract_version: str = SEMANTIC_REPRESENTATION_CONTRACT_VERSION,
    ) -> SemanticApplicationSnapshot:
        if record.schema_version not in {1, 2, SEMANTIC_STATE_SCHEMA_VERSION}:
            raise SemanticSnapshotValidationError(
                f"Unsupported semantic state schema version: {record.schema_version}"
            )
        if record.model_fingerprint != expected_model_fingerprint:
            raise SemanticPersistenceCompatibilityError(
                "Persisted embedding model fingerprint is incompatible"
            )
        if (
            record.representation_contract_version
            != expected_representation_contract_version
        ):
            raise SemanticPersistenceCompatibilityError(
                "Persisted representation contract is incompatible"
            )
        expected = {
            "runtime_states",
            "unknown_pool",
            "trusted_evidence",
            "constraints",
            "known_classes",
            "class_catalog",
            "pending_candidates",
            "suppressed_candidates",
        }
        if record.schema_version >= 2:
            expected.add("confirmed_memberships")
        if record.schema_version >= 3:
            expected.add("semantic_context_generation")
        _exact_keys(record.payload, expected, "payload")
        try:
            memberships = (
                tuple(self._decode(record.payload["confirmed_memberships"]))
                if record.schema_version >= 2
                else ()
            )
            runtime_payload = record.payload["runtime_states"]
            if record.schema_version < 3:
                runtime_payload = self._prepare_legacy_runtime_states(
                    runtime_payload,
                    memberships,
                )
            runtime_states = tuple(self._decode(runtime_payload))
            unknown_pool = self._decode(record.payload["unknown_pool"])
            pending_candidates = tuple(
                self._decode(record.payload["pending_candidates"])
            )
            if record.schema_version < 3:
                membership_by_topic = {
                    membership.topic: membership for membership in memberships
                }
                migrated_states = []
                for state in runtime_states:
                    membership = membership_by_topic.get(state.temporal_profile.topic)
                    decision = state.decision
                    if membership is not None and decision.reasons == (
                        SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
                    ):
                        decision = replace(
                            decision,
                            confirmed_class_id=membership.class_id,
                            confirmed_class_name=membership.semantic_class_name,
                        )
                    migrated_states.append(
                        replace(
                            state,
                            decision=decision,
                            semantic_context_generation=0,
                        )
                    )
                runtime_states = tuple(migrated_states)
                unknown_pool = replace(unknown_pool, entries=())
                pending_candidates = ()
            snapshot = SemanticApplicationSnapshot(
                metadata=SemanticPersistenceMetadata(
                    schema_version=SEMANTIC_STATE_SCHEMA_VERSION,
                    model_fingerprint=_required_text(
                        record.model_fingerprint, "model_fingerprint"
                    ),
                    representation_contract_version=_required_text(
                        record.representation_contract_version,
                        "representation_contract_version",
                    ),
                    policy_config=_plain_json(record.policy_config, "policy_config"),
                ),
                generation=_non_negative_int(record.generation, "generation"),
                semantic_context_generation=(
                    _non_negative_int(
                        record.payload["semantic_context_generation"],
                        "semantic_context_generation",
                    )
                    if record.schema_version >= 3
                    else 1
                ),
                runtime_states=runtime_states,
                unknown_pool=unknown_pool,
                trusted_evidence=tuple(
                    self._decode(record.payload["trusted_evidence"])
                ),
                constraints=tuple(self._decode(record.payload["constraints"])),
                confirmed_memberships=memberships,
                known_classes=tuple(self._decode(record.payload["known_classes"])),
                class_catalog=tuple(self._decode(record.payload["class_catalog"])),
                pending_candidates=pending_candidates,
                suppressed_candidates=tuple(
                    self._decode(record.payload["suppressed_candidates"])
                ),
            )
        except SemanticSnapshotValidationError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise SemanticSnapshotValidationError(
                f"Malformed semantic application snapshot: {exc}"
            ) from exc
        self.validate(snapshot)
        return snapshot

    def validate(self, snapshot: SemanticApplicationSnapshot) -> None:
        if not isinstance(snapshot, SemanticApplicationSnapshot):
            raise SemanticSnapshotValidationError(
                "snapshot must be a SemanticApplicationSnapshot"
            )
        if snapshot.metadata.schema_version != SEMANTIC_STATE_SCHEMA_VERSION:
            raise SemanticSnapshotValidationError(
                "Unsupported semantic state schema version"
            )
        _required_text(snapshot.metadata.model_fingerprint, "model_fingerprint")
        _required_text(
            snapshot.metadata.representation_contract_version,
            "representation_contract_version",
        )
        _non_negative_int(snapshot.generation, "generation")
        _non_negative_int(
            snapshot.semantic_context_generation,
            "semantic_context_generation",
        )
        _plain_json(dict(snapshot.metadata.policy_config), "policy_config")

        runtime_topics = [
            state.temporal_profile.topic for state in snapshot.runtime_states
        ]
        _unique(runtime_topics, "runtime topic")
        unknown_topics = [entry.topic for entry in snapshot.unknown_pool.entries]
        _unique(unknown_topics, "UNKNOWN topic")
        _non_negative_int(snapshot.unknown_pool.version, "UNKNOWN pool version")
        _unique(
            [
                (e.semantic_class_name, e.representation_name)
                for e in snapshot.trusted_evidence
            ],
            "trusted evidence identity",
        )
        _unique(
            [(c.topic, c.semantic_class_name) for c in snapshot.constraints],
            "constraint identity",
        )
        _unique(
            [membership.topic for membership in snapshot.confirmed_memberships],
            "confirmed membership topic",
        )
        _unique([c.class_id for c in snapshot.known_classes], "known class ID")
        _unique([c.class_id for c in snapshot.class_catalog], "catalog class ID")
        _unique(
            [c.semantic_class_name for c in snapshot.class_catalog],
            "catalog class name",
        )
        pending_ids = [c.identity for c in snapshot.pending_candidates]
        _unique(pending_ids, "pending candidate identity")
        _unique(snapshot.suppressed_candidates, "suppressed candidate identity")
        if set(pending_ids) & set(snapshot.suppressed_candidates):
            raise SemanticSnapshotValidationError(
                "A candidate cannot be both pending and suppressed"
            )

        membership_by_topic = {
            membership.topic: membership
            for membership in snapshot.confirmed_memberships
        }
        state_by_topic = {
            state.temporal_profile.topic: state for state in snapshot.runtime_states
        }
        dimensions: set[int] = set()
        for state in snapshot.runtime_states:
            _required_text(state.temporal_profile.topic, "runtime topic")
            self._validate_temporal(state.temporal_profile)
            self._validate_embeddings(state.embeddings, dimensions)
            self._validate_evidence(state.evidence)
            self._validate_consensus(state.consensus)
            self._validate_decision(state.decision)
            if state.semantic_context_generation > snapshot.semantic_context_generation:
                raise SemanticSnapshotValidationError(
                    "Runtime state semantic context exceeds application context"
                )
            if state.decision.confirmed_class_id is not None:
                membership = membership_by_topic.get(state.temporal_profile.topic)
                if (
                    membership is None
                    or membership.class_id != state.decision.confirmed_class_id
                    or membership.semantic_class_name
                    != state.decision.confirmed_class_name
                ):
                    raise SemanticSnapshotValidationError(
                        "Human-confirmed decision must match authoritative membership"
                    )
        for entry in snapshot.unknown_pool.entries:
            _required_text(entry.topic, "UNKNOWN topic")
            self._validate_embeddings(entry.embeddings, dimensions)
            self._validate_decision(entry.decision)
            if entry.decision.state is not SemanticClassDecisionState.UNKNOWN:
                raise SemanticSnapshotValidationError(
                    "UNKNOWN pool entry must contain an UNKNOWN decision"
                )
            state = state_by_topic.get(entry.topic)
            if (
                state is None
                or state.semantic_context_generation
                != snapshot.semantic_context_generation
            ):
                raise SemanticSnapshotValidationError(
                    "UNKNOWN pool cannot contain stale runtime evidence"
                )
        for known_class in snapshot.known_classes:
            _required_text(known_class.class_id, "class_id")
            _required_text(known_class.class_name, "class_name")
            self._validate_embeddings(known_class.centroids, dimensions)
        for evidence in snapshot.trusted_evidence:
            _required_text(evidence.semantic_class_name, "semantic_class_name")
            if evidence.representation_name not in REPRESENTATION_NAMES:
                raise SemanticSnapshotValidationError("Invalid representation name")
            _unique(evidence.member_topics, "trusted evidence member topic")
            for topic in evidence.member_topics:
                _required_text(topic, "member topic")
            dimensions.add(_vector(evidence.centroid, "trusted centroid"))
        for constraint in snapshot.constraints:
            _required_text(constraint.topic, "constraint topic")
            _required_text(constraint.semantic_class_name, "constraint class")
        catalog_by_id = {
            definition.class_id: definition.semantic_class_name
            for definition in snapshot.class_catalog
        }
        known_ids = {known_class.class_id for known_class in snapshot.known_classes}
        for membership in snapshot.confirmed_memberships:
            _required_text(membership.topic, "confirmed membership topic")
            _required_text(membership.class_id, "confirmed membership class_id")
            _required_text(
                membership.semantic_class_name,
                "confirmed membership class name",
            )
            if catalog_by_id.get(membership.class_id) != membership.semantic_class_name:
                raise SemanticSnapshotValidationError(
                    "Confirmed membership must reference the matching catalog class"
                )
            if membership.class_id not in known_ids:
                raise SemanticSnapshotValidationError(
                    "Confirmed membership must reference a known class"
                )
        for definition in snapshot.class_catalog:
            _required_text(definition.class_id, "catalog class_id")
            _required_text(definition.semantic_class_name, "catalog class name")
        for candidate in (*snapshot.pending_candidates,):
            self._validate_identity(candidate.identity)
            if candidate.candidate_index is not None:
                _non_negative_int(candidate.candidate_index, "candidate_index")
        for identity in snapshot.suppressed_candidates:
            self._validate_identity(identity)
        if len(dimensions) > 1:
            raise SemanticSnapshotValidationError(
                f"Inconsistent semantic vector dimensions: {sorted(dimensions)}"
            )

    def _validate_temporal(self, profile: TemporalStreamProfile) -> None:
        _non_negative_int(profile.observation_count, "temporal observation_count")
        identities = []
        for entry in profile.entries:
            if entry.source not in {"tag", "field"}:
                raise SemanticSnapshotValidationError("Invalid temporal source")
            if entry.current_value_type not in {
                "numeric",
                "boolean",
                "string",
                "null",
                "array",
                "object",
            }:
                raise SemanticSnapshotValidationError("Invalid temporal value type")
            _required_text(entry.normalized_key, "normalized_key")
            identities.append((entry.source, entry.normalized_key))
            for name in (
                "observation_count",
                "present_count",
                "missing_streak",
                "type_change_count",
                "value_change_count",
                "candidate_streak",
            ):
                _non_negative_int(getattr(entry, name), name)
        _unique(identities, "temporal entry identity")

    def _validate_embeddings(
        self, embeddings: RepresentationEmbeddings, dimensions: set[int]
    ) -> None:
        local = {
            _vector(getattr(embeddings, name), name) for name in REPRESENTATION_NAMES
        }
        if len(local) != 1:
            raise SemanticSnapshotValidationError(
                "All six representation vectors must have one dimension"
            )
        dimensions.update(local)

    def _validate_evidence(self, evidence: RepresentationClassEvidenceMatrix) -> None:
        _unique([row.class_id for row in evidence.rows], "evidence class ID")
        for row in evidence.rows:
            _required_text(row.class_id, "evidence class_id")
            _required_text(row.class_name, "evidence class_name")
            for value in row.scores.as_dict().values():
                _finite(value, "class score")

    def _validate_consensus(self, consensus: MultiViewConsensusResult) -> None:
        _unique([row.class_id for row in consensus.classes], "consensus class ID")
        _unique(
            [winner.representation_name for winner in consensus.view_winners],
            "consensus representation",
        )
        for winner in consensus.view_winners:
            if winner.representation_name not in REPRESENTATION_NAMES:
                raise SemanticSnapshotValidationError("Invalid representation name")
            _finite(winner.similarity, "winner similarity")
        for row in consensus.classes:
            _required_text(row.class_id, "consensus class_id")
            _required_text(row.class_name, "consensus class_name")
            _non_negative_int(row.top1_votes, "top1_votes")
            _finite(row.mean_rank, "mean_rank")
            _finite(row.mean_similarity, "mean_similarity")

    def _validate_decision(self, decision: SemanticClassDecision) -> None:
        if not isinstance(decision.state, SemanticClassDecisionState):
            raise SemanticSnapshotValidationError("Invalid decision state")
        if not decision.reasons or any(
            not isinstance(reason, SemanticClassDecisionReason)
            for reason in decision.reasons
        ):
            raise SemanticSnapshotValidationError("Invalid decision reasons")
        if decision.similarity_margin is not None:
            _finite(decision.similarity_margin, "similarity_margin")
        human_confirmed = decision.reasons == (
            SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP,
        )
        if human_confirmed:
            _required_text(decision.confirmed_class_id, "confirmed_class_id")
            _required_text(decision.confirmed_class_name, "confirmed_class_name")
            if decision.state is not SemanticClassDecisionState.KNOWN:
                raise SemanticSnapshotValidationError(
                    "Human-confirmed decision must be KNOWN"
                )
        elif (
            decision.confirmed_class_id is not None
            or decision.confirmed_class_name is not None
        ):
            raise SemanticSnapshotValidationError(
                "Automated decision cannot contain confirmed class identity"
            )

    @staticmethod
    def _validate_identity(identity: CandidateIdentity) -> None:
        if identity.representation_name not in REPRESENTATION_NAMES:
            raise SemanticSnapshotValidationError("Invalid representation name")
        _unique(identity.member_topics, "candidate member topic")
        for topic in identity.member_topics:
            _required_text(topic, "candidate member topic")

    @staticmethod
    def _prepare_legacy_runtime_states(runtime_payload, memberships):
        """Add only fields absent from schema 1/2 before strict decoding."""
        migrated = copy.deepcopy(runtime_payload)
        membership_by_topic = {
            membership.topic: membership for membership in memberships
        }
        for state in migrated:
            state.setdefault("semantic_context_generation", 0)
            decision = state["decision"]
            decision.setdefault("confirmed_class_id", None)
            decision.setdefault("confirmed_class_name", None)
            reasons = decision["reasons"]
            human_confirmed = len(reasons) == 1 and reasons[0].get("value") == (
                SemanticClassDecisionReason.HUMAN_CONFIRMED_MEMBERSHIP.value
            )
            if human_confirmed:
                topic = state["temporal_profile"]["topic"]
                membership = membership_by_topic.get(topic)
                if membership is not None:
                    decision["confirmed_class_id"] = membership.class_id
                    decision["confirmed_class_name"] = membership.semantic_class_name
        return migrated

    def _encode(self, value: Any) -> Any:
        if isinstance(value, Enum):
            if type(value).__name__ not in _ENUM_TYPES:
                raise SemanticSnapshotValidationError("Unsupported enum type")
            return {"_enum": type(value).__name__, "value": value.value}
        if is_dataclass(value):
            name = type(value).__name__
            if name not in _DATACLASS_TYPES:
                raise SemanticSnapshotValidationError(
                    f"Unsupported semantic state type: {name}"
                )
            encoded = {
                "_type": name,
                **{
                    field.name: self._encode(getattr(value, field.name))
                    for field in fields(value)
                },
            }
            if isinstance(value, TrustedClassEvidence):
                encoded["member_count"] = value.member_count
            return encoded
        if isinstance(value, tuple):
            return [self._encode(item) for item in value]
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, Real):
            return _finite(value, "numeric value")
        raise SemanticSnapshotValidationError(
            f"Unsupported semantic state value: {type(value).__name__}"
        )

    def _decode(self, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(self._decode(item) for item in value)
        if isinstance(value, dict):
            if "_enum" in value:
                _exact_keys(value, {"_enum", "value"}, "enum")
                enum_type = _ENUM_TYPES.get(value["_enum"])
                if enum_type is None:
                    raise SemanticSnapshotValidationError("Unknown enum type")
                try:
                    return enum_type(value["value"])
                except (TypeError, ValueError) as exc:
                    raise SemanticSnapshotValidationError("Invalid enum value") from exc
            name = value.get("_type")
            cls = _DATACLASS_TYPES.get(name)
            if cls is None:
                raise SemanticSnapshotValidationError("Unknown semantic state type")
            expected = {"_type", *(field.name for field in fields(cls))}
            if cls is TrustedClassEvidence:
                expected.add("member_count")
            optional_defaults = {}
            if cls is SemanticRuntimeTopicState:
                optional_defaults["semantic_context_generation"] = 0
            if cls is SemanticClassDecision:
                optional_defaults.update(
                    confirmed_class_id=None,
                    confirmed_class_name=None,
                )
            if cls is PendingSemanticCandidate:
                optional_defaults["retained_after_review"] = False
            for optional_name in optional_defaults:
                if optional_name not in value:
                    expected.remove(optional_name)
            _exact_keys(value, expected, name)
            kwargs = {
                field.name: self._decode(value[field.name])
                for field in fields(cls)
                if field.name in value
            }
            kwargs = {**optional_defaults, **kwargs}
            if cls is TrustedClassEvidence:
                member_count = _non_negative_int(
                    value["member_count"], "trusted evidence member_count"
                )
                if member_count != len(kwargs["member_topics"]):
                    raise SemanticSnapshotValidationError(
                        "Trusted evidence member_count does not match member_topics"
                    )
            try:
                return cls(**kwargs)
            except (TypeError, ValueError) as exc:
                raise SemanticSnapshotValidationError(f"Invalid {name}: {exc}") from exc
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, Real):
            return _finite(value, "numeric value")
        raise SemanticSnapshotValidationError("Invalid JSON snapshot value")


class SemanticStateRepository(ABC):
    """Storage abstraction for one generation-guarded application snapshot."""

    @abstractmethod
    def load(self, state_key: str) -> SemanticPersistenceRecord | None: ...

    @abstractmethod
    def save(self, record: SemanticPersistenceRecord) -> bool: ...

    def delete(self, state_key: str) -> bool:
        raise NotImplementedError

    def health(self) -> bool:
        return True


class InMemorySemanticStateRepository(SemanticStateRepository):
    """Thread-safe deterministic repository for isolated and restart tests."""

    def __init__(self) -> None:
        self._records: dict[str, SemanticPersistenceRecord] = {}
        self._lock = RLock()

    def load(self, state_key: str) -> SemanticPersistenceRecord | None:
        with self._lock:
            return copy.deepcopy(
                self._records.get(_required_text(state_key, "state_key"))
            )

    def save(self, record: SemanticPersistenceRecord) -> bool:
        with self._lock:
            existing = self._records.get(record.state_key)
            if existing is not None and existing.generation > record.generation:
                return False
            self._records[record.state_key] = copy.deepcopy(record)
            return True

    def delete(self, state_key: str) -> bool:
        with self._lock:
            return self._records.pop(state_key, None) is not None


class PostgresSemanticStateRepository(SemanticStateRepository):
    """PostgreSQL JSONB snapshot repository; construction performs no I/O."""

    def __init__(self, postgres_client) -> None:
        self._client = postgres_client

    def load(self, state_key: str) -> SemanticPersistenceRecord | None:
        validated_key = _required_text(state_key, "state_key")
        try:
            row = self._client.fetch_one(
                """SELECT state_key, schema_version, generation, model_fingerprint,
                          representation_contract_version, policy_config, payload,
                          updated_at
                     FROM semantic_application_state WHERE state_key = %s""",
                (validated_key,),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load semantic state key '{validated_key}'"
            ) from exc
        if row is None:
            return None
        return SemanticPersistenceRecord(
            state_key=row["state_key"],
            schema_version=row["schema_version"],
            generation=row["generation"],
            model_fingerprint=row["model_fingerprint"],
            representation_contract_version=row["representation_contract_version"],
            policy_config=_json_object(row["policy_config"], "policy_config"),
            payload=_json_object(row["payload"], "payload"),
            updated_at=row["updated_at"],
        )

    def save(self, record: SemanticPersistenceRecord) -> bool:
        sql = """INSERT INTO semantic_application_state (
                    state_key, schema_version, generation, model_fingerprint,
                    representation_contract_version, policy_config, payload, updated_at
                 ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT (state_key) DO UPDATE SET
                    schema_version = EXCLUDED.schema_version,
                    generation = EXCLUDED.generation,
                    model_fingerprint = EXCLUDED.model_fingerprint,
                    representation_contract_version = EXCLUDED.representation_contract_version,
                    policy_config = EXCLUDED.policy_config,
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                 WHERE semantic_application_state.generation <= EXCLUDED.generation"""
        try:
            with self._client.transaction() as conn:
                cursor = conn.execute(
                    sql,
                    (
                        record.state_key,
                        record.schema_version,
                        record.generation,
                        record.model_fingerprint,
                        record.representation_contract_version,
                        Jsonb(record.policy_config),
                        Jsonb(record.payload),
                        record.updated_at,
                    ),
                )
                return cursor.rowcount > 0
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save semantic state key '{record.state_key}' "
                f"generation {record.generation}"
            ) from exc

    def delete(self, state_key: str) -> bool:
        return (
            self._client.execute(
                "DELETE FROM semantic_application_state WHERE state_key = %s",
                (_required_text(state_key, "state_key"),),
            )
            > 0
        )

    def health(self) -> bool:
        try:
            self._client.fetch_one("SELECT 1 FROM semantic_application_state LIMIT 1")
            return True
        except Exception:  # noqa: BLE001 - health probes collapse dependency errors
            return False


def create_model_fingerprint(
    model_identifier: str,
    representation_contract_version: str = SEMANTIC_REPRESENTATION_CONTRACT_VERSION,
) -> str:
    """Return a stable, machine-independent compatibility fingerprint."""
    import hashlib

    source = json.dumps(
        {
            "embedding_model": _required_text(model_identifier, "model_identifier"),
            "representation_contract_version": _required_text(
                representation_contract_version, "representation_contract_version"
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticSnapshotValidationError(f"{name} must be a non-empty string")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SemanticSnapshotValidationError(f"{name} must be a non-negative integer")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SemanticSnapshotValidationError(f"{name} must be numeric and finite")
    result = float(value)
    if not math.isfinite(result):
        raise SemanticSnapshotValidationError(f"{name} must be numeric and finite")
    return result


def _vector(values: Any, name: str) -> int:
    if not isinstance(values, tuple) or not values:
        raise SemanticSnapshotValidationError(f"{name} must be a non-empty vector")
    for value in values:
        _finite(value, name)
    return len(values)


def _unique(values, name: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise SemanticSnapshotValidationError(f"Duplicate {name}")


def _exact_keys(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise SemanticSnapshotValidationError(
            f"Invalid {name} fields; missing={missing}, extra={extra}"
        )


def _plain_json(value: Any, name: str) -> Any:
    try:
        encoded = json.dumps(value, sort_keys=True, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise SemanticSnapshotValidationError(
            f"{name} must contain deterministic JSON-compatible values"
        ) from exc


def _json_object(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise SemanticSnapshotValidationError(f"{name} must be a JSON object")
    return value
