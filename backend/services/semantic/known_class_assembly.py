"""Materialize complete known classes from trusted six-view evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .representation_class_scoring import RepresentationClassCentroids
from .representation_embedder import RepresentationEmbeddings
from .trusted_class_evidence import TrustedClassEvidenceStore

_REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


@dataclass(frozen=True, slots=True)
class KnownClassAssemblyRequest:
    """Explicit identity for a requested known-class materialization."""

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


@dataclass(frozen=True, slots=True)
class KnownClassAssemblyResult:
    """Complete centroids or the deterministically ordered missing views."""

    class_id: str
    semantic_class_name: str
    missing_representations: tuple[str, ...]
    centroids: RepresentationClassCentroids | None

    @property
    def is_complete(self) -> bool:
        """Return whether all six views produced scorer-ready centroids."""
        return not self.missing_representations and self.centroids is not None


class KnownClassAssembler:
    """Read trusted evidence without altering it or synthesizing missing views."""

    def assemble(
        self,
        request: KnownClassAssemblyRequest,
        evidence_store: TrustedClassEvidenceStore,
    ) -> KnownClassAssemblyResult:
        """Return complete centroids only when every representation is present."""
        evidence = tuple(
            evidence_store.get(request.semantic_class_name, representation_name)
            for representation_name in _REPRESENTATION_NAMES
        )
        missing_representations = tuple(
            representation_name
            for representation_name, item in zip(
                _REPRESENTATION_NAMES,
                evidence,
                strict=True,
            )
            if item is None
        )
        if missing_representations:
            return KnownClassAssemblyResult(
                class_id=request.class_id,
                semantic_class_name=request.semantic_class_name,
                missing_representations=missing_representations,
                centroids=None,
            )

        return KnownClassAssemblyResult(
            class_id=request.class_id,
            semantic_class_name=request.semantic_class_name,
            missing_representations=(),
            centroids=RepresentationClassCentroids(
                class_id=request.class_id,
                class_name=request.semantic_class_name,
                centroids=RepresentationEmbeddings(
                    value_only=evidence[0].centroid,
                    key_only=evidence[1].centroid,
                    key_value=evidence[2].centroid,
                    schema=evidence[3].centroid,
                    numeric_key_only=evidence[4].centroid,
                    topic_key_value=evidence[5].centroid,
                ),
            ),
        )
