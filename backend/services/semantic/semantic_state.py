"""Application-wide coordination and immutable semantic state snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .candidate_confirmation import CandidateIdentity
    from .confirmed_membership import ConfirmedSemanticMembership
    from .known_class_registry import SemanticClassDefinition
    from .representation_class_scoring import RepresentationClassCentroids
    from .semantic_feedback_workflow import NegativeMembershipConstraint
    from .semantic_review_runtime import PendingSemanticCandidate
    from .semantic_runtime import SemanticRuntimeTopicState
    from .trusted_class_evidence import TrustedClassEvidence
    from .unknown_stream_pool import UnknownStreamPoolSnapshot

SEMANTIC_STATE_SCHEMA_VERSION = 2
SEMANTIC_REPRESENTATION_CONTRACT_VERSION = "smartmqtt-six-view-v1"


@dataclass(frozen=True, slots=True)
class SemanticPersistenceMetadata:
    """Compatibility and diagnostic metadata stored with one snapshot."""

    schema_version: int
    model_fingerprint: str
    representation_contract_version: str
    policy_config: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SemanticApplicationSnapshot:
    """Complete authoritative state captured at one application generation."""

    metadata: SemanticPersistenceMetadata
    generation: int
    runtime_states: tuple[SemanticRuntimeTopicState, ...]
    unknown_pool: UnknownStreamPoolSnapshot
    trusted_evidence: tuple[TrustedClassEvidence, ...]
    constraints: tuple[NegativeMembershipConstraint, ...]
    confirmed_memberships: tuple[ConfirmedSemanticMembership, ...]
    known_classes: tuple[RepresentationClassCentroids, ...]
    class_catalog: tuple[SemanticClassDefinition, ...]
    pending_candidates: tuple[PendingSemanticCandidate, ...]
    suppressed_candidates: tuple[CandidateIdentity, ...]


class SemanticStateCoordinator:
    """Coordinate logical mutations and monotonic application generations."""

    def __init__(self, generation: int = 0) -> None:
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise TypeError("generation must be an integer")
        if generation < 0:
            raise ValueError("generation must be non-negative")
        self.lock = RLock()
        self._generation = generation
        self._depth = 0
        self._dirty = False
        self._listeners: list[Callable[[int], None]] = []

    @property
    def generation(self) -> int:
        with self.lock:
            return self._generation

    def add_listener(self, listener: Callable[[int], None]) -> None:
        with self.lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Coalesce nested successful content changes into one generation."""
        listeners: tuple[Callable[[int], None], ...] = ()
        generation: int | None = None
        with self.lock:
            outer = self._depth == 0
            prior_dirty = self._dirty
            self._depth += 1
            try:
                yield
            except Exception:
                self._dirty = prior_dirty
                raise
            finally:
                self._depth -= 1
                if outer and self._depth == 0:
                    if self._dirty:
                        self._generation += 1
                        generation = self._generation
                        listeners = tuple(self._listeners)
                    self._dirty = False
        if generation is not None:
            for listener in listeners:
                listener(generation)

    def mark_changed(self) -> None:
        """Record one content change, immediately or in the active transaction."""
        listeners: tuple[Callable[[int], None], ...] = ()
        generation: int | None = None
        with self.lock:
            if self._depth:
                self._dirty = True
                return
            self._generation += 1
            generation = self._generation
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(generation)

    @contextmanager
    def restore(self, generation: int) -> Iterator[None]:
        """Apply validated replacement operations without mutation notifications."""
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise TypeError("generation must be an integer")
        if generation < 0:
            raise ValueError("generation must be non-negative")
        with self.lock:
            previous_generation = self._generation
            previous_depth = self._depth
            previous_dirty = self._dirty
            self._depth += 1
            self._dirty = False
            try:
                yield
            except Exception:
                self._generation = previous_generation
                raise
            else:
                self._generation = generation
            finally:
                self._depth = previous_depth
                self._dirty = previous_dirty
