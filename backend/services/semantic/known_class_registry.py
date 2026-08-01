"""Thread-safe explicit known-class identity and centroid registries."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .representation_class_scoring import RepresentationClassCentroids


class KnownClassRegistry:
    """Latest immutable six-view centroids keyed explicitly by class ID."""

    def __init__(
        self, initial: tuple[RepresentationClassCentroids, ...] = (), coordinator=None
    ) -> None:
        self._classes: dict[str, RepresentationClassCentroids] = {}
        self._lock = RLock()
        self._coordinator = coordinator
        for known_class in initial:
            self.upsert(known_class)

    def upsert(self, known_class: RepresentationClassCentroids) -> None:
        if not isinstance(known_class, RepresentationClassCentroids):
            raise TypeError("known_class must be RepresentationClassCentroids")
        with self._lock:
            changed = self._classes.get(known_class.class_id) != known_class
            self._classes[known_class.class_id] = known_class
        if changed and self._coordinator is not None:
            self._coordinator.mark_changed()

    def get(self, class_id: str) -> RepresentationClassCentroids | None:
        with self._lock:
            return self._classes.get(class_id)

    def remove(self, class_id: str) -> RepresentationClassCentroids | None:
        with self._lock:
            removed = self._classes.pop(class_id, None)
        if removed is not None and self._coordinator is not None:
            self._coordinator.mark_changed()
        return removed

    def all(self) -> tuple[RepresentationClassCentroids, ...]:
        return self.snapshot()

    def snapshot(self) -> tuple[RepresentationClassCentroids, ...]:
        with self._lock:
            return tuple(self._classes[key] for key in sorted(self._classes))

    def replace(self, classes: tuple[RepresentationClassCentroids, ...]) -> None:
        replacement = {known_class.class_id: known_class for known_class in classes}
        if len(replacement) != len(classes):
            raise ValueError("Known class snapshot contains duplicate class_id")
        with self._lock:
            if self._classes == replacement:
                return
            self._classes = replacement
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def __len__(self) -> int:
        with self._lock:
            return len(self._classes)


@dataclass(frozen=True, slots=True)
class SemanticClassDefinition:
    """Explicit stable mapping between class ID and semantic class name."""

    class_id: str
    semantic_class_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.class_id, str) or not self.class_id.strip():
            raise ValueError("class_id must be a non-empty string")
        if (
            not isinstance(self.semantic_class_name, str)
            or not self.semantic_class_name.strip()
        ):
            raise ValueError("semantic_class_name must be a non-empty string")


class SemanticClassCatalog:
    """Thread-safe bijection of explicit class IDs and class names."""

    def __init__(
        self, initial: tuple[SemanticClassDefinition, ...] = (), coordinator=None
    ) -> None:
        self._by_id: dict[str, SemanticClassDefinition] = {}
        self._id_by_name: dict[str, str] = {}
        self._lock = RLock()
        self._coordinator = coordinator
        for definition in initial:
            self.register(definition)

    def register(self, definition: SemanticClassDefinition) -> None:
        if not isinstance(definition, SemanticClassDefinition):
            raise TypeError("definition must be a SemanticClassDefinition")
        with self._lock:
            existing_id = self._by_id.get(definition.class_id)
            if existing_id is not None and existing_id != definition:
                raise ValueError(
                    f"class_id '{definition.class_id}' is already mapped to "
                    f"'{existing_id.semantic_class_name}'"
                )
            existing_name_id = self._id_by_name.get(definition.semantic_class_name)
            if existing_name_id is not None and existing_name_id != definition.class_id:
                raise ValueError(
                    f"semantic_class_name '{definition.semantic_class_name}' is already "
                    f"mapped to '{existing_name_id}'"
                )
            self._by_id[definition.class_id] = definition
            self._id_by_name[definition.semantic_class_name] = definition.class_id
        if existing_id != definition and self._coordinator is not None:
            self._coordinator.mark_changed()

    def get(self, class_id: str) -> SemanticClassDefinition | None:
        with self._lock:
            return self._by_id.get(class_id)

    def get_by_name(self, semantic_class_name: str) -> SemanticClassDefinition | None:
        with self._lock:
            class_id = self._id_by_name.get(semantic_class_name)
            return self._by_id.get(class_id) if class_id is not None else None

    def all(self) -> tuple[SemanticClassDefinition, ...]:
        return self.snapshot()

    def snapshot(self) -> tuple[SemanticClassDefinition, ...]:
        with self._lock:
            return tuple(self._by_id[key] for key in sorted(self._by_id))

    def replace(self, definitions: tuple[SemanticClassDefinition, ...]) -> None:
        by_id: dict[str, SemanticClassDefinition] = {}
        by_name: dict[str, str] = {}
        for definition in definitions:
            if definition.class_id in by_id:
                raise ValueError("Catalog snapshot contains duplicate class_id")
            if definition.semantic_class_name in by_name:
                raise ValueError(
                    "Catalog snapshot contains duplicate semantic_class_name"
                )
            by_id[definition.class_id] = definition
            by_name[definition.semantic_class_name] = definition.class_id
        with self._lock:
            if self._by_id == by_id:
                return
            self._by_id = by_id
            self._id_by_name = by_name
        if self._coordinator is not None:
            self._coordinator.mark_changed()

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)
