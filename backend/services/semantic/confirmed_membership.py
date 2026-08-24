"""Authoritative human-confirmed semantic membership state."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class ConfirmedSemanticMembership:
    """One deterministic human-confirmed topic-to-class assignment."""

    topic: str
    class_id: str
    semantic_class_name: str

    def __post_init__(self) -> None:
        for name in ("topic", "class_id", "semantic_class_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


class ConfirmedSemanticMembershipStore:
    """Latest authoritative human assignment keyed by topic."""

    def __init__(self, coordinator=None) -> None:
        self._memberships: dict[str, ConfirmedSemanticMembership] = {}
        self._lock = RLock()
        self._coordinator = coordinator

    def get(self, topic: str) -> ConfirmedSemanticMembership | None:
        with self._lock:
            return self._memberships.get(topic)

    def upsert(self, membership: ConfirmedSemanticMembership) -> None:
        with self._lock:
            if self._memberships.get(membership.topic) == membership:
                return
            self._memberships[membership.topic] = membership
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def remove(self, topic: str) -> ConfirmedSemanticMembership | None:
        with self._lock:
            removed = self._memberships.pop(topic, None)
        if removed is not None and self._coordinator is not None:
            self._coordinator.mark_changed()
        return removed

    def all(self) -> tuple[ConfirmedSemanticMembership, ...]:
        with self._lock:
            return tuple(
                self._memberships[topic] for topic in sorted(self._memberships)
            )

    def snapshot(self) -> tuple[ConfirmedSemanticMembership, ...]:
        return self.all()

    def replace(self, memberships: tuple[ConfirmedSemanticMembership, ...]) -> None:
        replacement = {membership.topic: membership for membership in memberships}
        if len(replacement) != len(memberships):
            raise ValueError("Confirmed membership snapshot contains duplicate topics")
        with self._lock:
            if self._memberships == replacement:
                return
            self._memberships = replacement
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def __len__(self) -> int:
        with self._lock:
            return len(self._memberships)
