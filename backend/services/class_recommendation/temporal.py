"""Deterministic temporal evidence for repeated stream profile observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .profiling import FieldProfile, ProfileSource, StreamProfile, ValueType


class TemporalChangeType(str, Enum):
    """Explicit evidence types emitted by temporal profile updates."""

    KEY_ADDED = "KEY_ADDED"
    KEY_MISSING = "KEY_MISSING"
    KEY_REAPPEARED = "KEY_REAPPEARED"
    VALUE_CHANGED = "VALUE_CHANGED"
    TYPE_CHANGED = "TYPE_CHANGED"
    STABLE_VALUE_ESTABLISHED = "STABLE_VALUE_ESTABLISHED"
    STABLE_VALUE_CHANGED = "STABLE_VALUE_CHANGED"


@dataclass(frozen=True, slots=True)
class TemporalEntryState:
    """Bounded temporal state for one source and normalized key."""

    source: ProfileSource
    normalized_key: str
    observation_count: int
    present_count: int
    missing_streak: int
    current_value_type: ValueType
    type_change_count: int
    last_normalized_value: str
    value_change_count: int
    stable_value: str | None
    candidate_value: str | None
    candidate_streak: int
    is_identifier_like: bool
    is_unit_like: bool
    is_timestamp_like: bool

    @property
    def is_numeric(self) -> bool:
        """Compatibility view derived from datatype; not recommendation evidence."""
        return self.current_value_type == "numeric"


@dataclass(frozen=True, slots=True)
class TemporalStreamProfile:
    """Immutable temporal state for one stream topic."""

    topic: str
    observation_count: int
    entries: tuple[TemporalEntryState, ...]


@dataclass(frozen=True, slots=True)
class TemporalChange:
    """One ordered piece of temporal evidence for a stream entry."""

    change_type: TemporalChangeType
    source: ProfileSource
    normalized_key: str
    previous_value: str | None = None
    current_value: str | None = None
    previous_value_type: ValueType | None = None
    current_value_type: ValueType | None = None
    previous_missing_streak: int | None = None


@dataclass(frozen=True, slots=True)
class TemporalProfileUpdate:
    """Updated temporal profile and changes observed in one update."""

    profile: TemporalStreamProfile
    changes: tuple[TemporalChange, ...]


class TemporalStreamProfiler:
    """Update bounded temporal state from immutable stream observations."""

    def __init__(self, stable_value_observations: int = 3):
        if (
            isinstance(stable_value_observations, bool)
            or not isinstance(stable_value_observations, int)
            or stable_value_observations < 1
        ):
            raise ValueError("stable_value_observations must be at least 1")
        self.stable_value_observations = stable_value_observations

    def update(
        self,
        previous: TemporalStreamProfile | None,
        observation: StreamProfile,
    ) -> TemporalProfileUpdate:
        """Return the next immutable state and deterministic evidence events."""
        if previous is not None and previous.topic != observation.topic:
            raise ValueError(
                "Previous temporal profile topic does not match observation topic"
            )

        previous_entries = (
            self._state_map(previous.entries) if previous is not None else {}
        )
        observed_entries = self._observation_map(observation.entries)
        identities = sorted(
            previous_entries.keys() | observed_entries.keys(),
            key=self._identity_sort_key,
        )

        updated_entries = []
        changes = []
        for identity in identities:
            old_state = previous_entries.get(identity)
            field = observed_entries.get(identity)
            if field is None:
                updated_entries.append(
                    replace(
                        old_state,
                        observation_count=old_state.observation_count + 1,
                        missing_streak=old_state.missing_streak + 1,
                    )
                )
                changes.append(
                    TemporalChange(
                        change_type=TemporalChangeType.KEY_MISSING,
                        source=old_state.source,
                        normalized_key=old_state.normalized_key,
                        previous_value=old_state.last_normalized_value,
                        previous_value_type=old_state.current_value_type,
                    )
                )
            elif old_state is None:
                updated_entries.append(self._new_state(field))
                changes.append(
                    TemporalChange(
                        change_type=TemporalChangeType.KEY_ADDED,
                        source=field.source,
                        normalized_key=field.normalized_key,
                        current_value=field.normalized_value,
                        current_value_type=field.value_type,
                    )
                )
            else:
                state, entry_changes = self._update_present(old_state, field)
                updated_entries.append(state)
                changes.extend(entry_changes)

        observation_count = (
            previous.observation_count + 1 if previous is not None else 1
        )
        return TemporalProfileUpdate(
            profile=TemporalStreamProfile(
                topic=observation.topic,
                observation_count=observation_count,
                entries=tuple(updated_entries),
            ),
            changes=tuple(changes),
        )

    def _new_state(self, field: FieldProfile) -> TemporalEntryState:
        stable_value, candidate_value, candidate_streak, _ = self._advance_hysteresis(
            stable_value=None,
            candidate_value=None,
            candidate_streak=0,
            normalized_value=field.normalized_value,
            categorical=self._uses_categorical_stability(field),
        )
        return TemporalEntryState(
            source=field.source,
            normalized_key=field.normalized_key,
            observation_count=1,
            present_count=1,
            missing_streak=0,
            current_value_type=field.value_type,
            type_change_count=0,
            last_normalized_value=field.normalized_value,
            value_change_count=0,
            stable_value=stable_value,
            candidate_value=candidate_value,
            candidate_streak=candidate_streak,
            is_identifier_like=field.is_identifier_like,
            is_unit_like=field.is_unit_like,
            is_timestamp_like=field.is_timestamp_like,
        )

    def _update_present(
        self,
        old_state: TemporalEntryState,
        field: FieldProfile,
    ) -> tuple[TemporalEntryState, tuple[TemporalChange, ...]]:
        changes = []
        type_changed = old_state.current_value_type != field.value_type
        value_changed = old_state.last_normalized_value != field.normalized_value

        if old_state.missing_streak > 0:
            changes.append(
                TemporalChange(
                    change_type=TemporalChangeType.KEY_REAPPEARED,
                    source=field.source,
                    normalized_key=field.normalized_key,
                    previous_missing_streak=old_state.missing_streak,
                )
            )
        if type_changed:
            changes.append(
                TemporalChange(
                    change_type=TemporalChangeType.TYPE_CHANGED,
                    source=field.source,
                    normalized_key=field.normalized_key,
                    previous_value_type=old_state.current_value_type,
                    current_value_type=field.value_type,
                )
            )
        if value_changed:
            changes.append(
                TemporalChange(
                    change_type=TemporalChangeType.VALUE_CHANGED,
                    source=field.source,
                    normalized_key=field.normalized_key,
                    previous_value=old_state.last_normalized_value,
                    current_value=field.normalized_value,
                )
            )

        stable_value, candidate_value, candidate_streak, stable_changed = (
            self._advance_hysteresis(
                stable_value=old_state.stable_value,
                candidate_value=old_state.candidate_value,
                candidate_streak=old_state.candidate_streak,
                normalized_value=field.normalized_value,
                categorical=self._uses_categorical_stability(field),
            )
        )
        stable_established = old_state.stable_value is None and stable_value is not None
        if stable_established:
            changes.append(
                TemporalChange(
                    change_type=TemporalChangeType.STABLE_VALUE_ESTABLISHED,
                    source=field.source,
                    normalized_key=field.normalized_key,
                    current_value=stable_value,
                )
            )
        if stable_changed:
            changes.append(
                TemporalChange(
                    change_type=TemporalChangeType.STABLE_VALUE_CHANGED,
                    source=field.source,
                    normalized_key=field.normalized_key,
                    previous_value=old_state.stable_value,
                    current_value=stable_value,
                )
            )

        return (
            TemporalEntryState(
                source=field.source,
                normalized_key=field.normalized_key,
                observation_count=old_state.observation_count + 1,
                present_count=old_state.present_count + 1,
                missing_streak=0,
                current_value_type=field.value_type,
                type_change_count=old_state.type_change_count + int(type_changed),
                last_normalized_value=field.normalized_value,
                value_change_count=old_state.value_change_count + int(value_changed),
                stable_value=stable_value,
                candidate_value=candidate_value,
                candidate_streak=candidate_streak,
                is_identifier_like=field.is_identifier_like,
                is_unit_like=field.is_unit_like,
                is_timestamp_like=field.is_timestamp_like,
            ),
            tuple(changes),
        )

    def _advance_hysteresis(
        self,
        *,
        stable_value: str | None,
        candidate_value: str | None,
        candidate_streak: int,
        normalized_value: str,
        categorical: bool,
    ) -> tuple[str | None, str | None, int, bool]:
        if not categorical:
            return None, None, 0, False
        if normalized_value == stable_value:
            return stable_value, None, 0, False

        if normalized_value == candidate_value:
            next_streak = candidate_streak + 1
        else:
            candidate_value = normalized_value
            next_streak = 1

        if next_streak < self.stable_value_observations:
            return stable_value, candidate_value, next_streak, False

        stable_changed = stable_value is not None and stable_value != candidate_value
        return candidate_value, None, 0, stable_changed

    @staticmethod
    def _uses_categorical_stability(field: FieldProfile) -> bool:
        # Numeric sensor readings are volatile telemetry; the datatype drives this
        # temporal policy directly instead of a recommendation-specific boolean flag.
        return not (field.source == "field" and field.value_type == "numeric")

    @classmethod
    def _observation_map(
        cls,
        entries: tuple[FieldProfile, ...],
    ) -> dict[tuple[ProfileSource, str], FieldProfile]:
        mapped = {}
        for entry in entries:
            identity = (entry.source, entry.normalized_key)
            if identity in mapped:
                raise ValueError(
                    "Observation contains duplicate temporal identity: "
                    f"{entry.source}:{entry.normalized_key}"
                )
            mapped[identity] = entry
        return mapped

    @staticmethod
    def _state_map(
        entries: tuple[TemporalEntryState, ...],
    ) -> dict[tuple[ProfileSource, str], TemporalEntryState]:
        mapped = {}
        for entry in entries:
            identity = (entry.source, entry.normalized_key)
            if identity in mapped:
                raise ValueError(
                    "Temporal profile contains duplicate identity: "
                    f"{entry.source}:{entry.normalized_key}"
                )
            mapped[identity] = entry
        return mapped

    @staticmethod
    def _identity_sort_key(
        identity: tuple[ProfileSource, str],
    ) -> tuple[int, str]:
        source, normalized_key = identity
        return (0 if source == "tag" else 1, normalized_key)
