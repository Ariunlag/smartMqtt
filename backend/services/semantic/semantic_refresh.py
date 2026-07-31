"""Deterministic refresh decisions derived from temporal stream evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .stream_profiler import ProfileSource, ValueType
from .temporal_profile import (
    TemporalChange,
    TemporalChangeType,
    TemporalEntryState,
    TemporalProfileUpdate,
)


class SemanticRefreshReasonType(str, Enum):
    """Explicit causes for requesting semantic representation refresh."""

    INITIAL_OBSERVATION = "INITIAL_OBSERVATION"
    KEY_ADDED = "KEY_ADDED"
    KEY_MISSING_PERSISTED = "KEY_MISSING_PERSISTED"
    TYPE_CHANGED = "TYPE_CHANGED"
    STABLE_VALUE_CHANGED = "STABLE_VALUE_CHANGED"


@dataclass(frozen=True, slots=True)
class SemanticRefreshReason:
    """One ordered, diagnostic reason for a semantic refresh decision."""

    reason_type: SemanticRefreshReasonType
    source: ProfileSource | None = None
    normalized_key: str | None = None
    previous_value: str | None = None
    current_value: str | None = None
    previous_value_type: ValueType | None = None
    current_value_type: ValueType | None = None


@dataclass(frozen=True, slots=True)
class SemanticRefreshDecision:
    """Immutable refresh decision with deterministic supporting reasons."""

    should_refresh: bool
    reasons: tuple[SemanticRefreshReason, ...]


class SemanticRefreshPolicy:
    """Convert temporal evidence into deterministic semantic refresh decisions."""

    def __init__(self, missing_observations_before_refresh: int = 3):
        if (
            isinstance(missing_observations_before_refresh, bool)
            or not isinstance(missing_observations_before_refresh, int)
            or missing_observations_before_refresh < 1
        ):
            raise ValueError("missing_observations_before_refresh must be at least 1")
        self.missing_observations_before_refresh = missing_observations_before_refresh

    def evaluate(self, update: TemporalProfileUpdate) -> SemanticRefreshDecision:
        """Return whether the update warrants refresh and explain every cause."""
        if update.profile.observation_count == 1:
            return SemanticRefreshDecision(
                should_refresh=True,
                reasons=(
                    SemanticRefreshReason(
                        SemanticRefreshReasonType.INITIAL_OBSERVATION
                    ),
                ),
            )

        entry_states = {
            (entry.source, entry.normalized_key): entry
            for entry in update.profile.entries
        }
        reasons = []
        for change in update.changes:
            reason_type = self._reason_type(change, entry_states)
            if reason_type is not None:
                reasons.append(self._reason(reason_type, change))

        frozen_reasons = tuple(reasons)
        return SemanticRefreshDecision(
            should_refresh=bool(frozen_reasons),
            reasons=frozen_reasons,
        )

    def _reason_type(
        self,
        change: TemporalChange,
        entry_states: dict[tuple[ProfileSource, str], TemporalEntryState],
    ) -> SemanticRefreshReasonType | None:
        if change.change_type == TemporalChangeType.KEY_ADDED:
            return SemanticRefreshReasonType.KEY_ADDED
        if change.change_type == TemporalChangeType.TYPE_CHANGED:
            return SemanticRefreshReasonType.TYPE_CHANGED
        if change.change_type == TemporalChangeType.STABLE_VALUE_CHANGED:
            return SemanticRefreshReasonType.STABLE_VALUE_CHANGED
        if change.change_type != TemporalChangeType.KEY_MISSING:
            return None

        state = entry_states[(change.source, change.normalized_key)]
        if state.missing_streak == self.missing_observations_before_refresh:
            return SemanticRefreshReasonType.KEY_MISSING_PERSISTED
        return None

    @staticmethod
    def _reason(
        reason_type: SemanticRefreshReasonType,
        change: TemporalChange,
    ) -> SemanticRefreshReason:
        return SemanticRefreshReason(
            reason_type=reason_type,
            source=change.source,
            normalized_key=change.normalized_key,
            previous_value=change.previous_value,
            current_value=change.current_value,
            previous_value_type=change.previous_value_type,
            current_value_type=change.current_value_type,
        )
