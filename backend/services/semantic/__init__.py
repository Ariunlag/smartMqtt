"""Deterministic structural profiling and textual representations for SmartMQTT streams."""

from .pipeline import StreamSemanticPipeline, StreamSemanticPipelineResult
from .representation_embedder import RepresentationEmbedder, RepresentationEmbeddings
from .representations import RepresentationBuilder, StreamRepresentations
from .stream_class import (
    ClassMatch,
    StreamClassEngine,
    StreamClassMember,
    StreamSemanticClass,
)
from .stream_profiler import FieldProfile, StreamProfile, StreamProfiler, normalize_text
from .temporal_profile import (
    TemporalChange,
    TemporalChangeType,
    TemporalEntryState,
    TemporalProfileUpdate,
    TemporalStreamProfile,
    TemporalStreamProfiler,
)

__all__ = [
    "ClassMatch",
    "FieldProfile",
    "RepresentationBuilder",
    "RepresentationEmbedder",
    "RepresentationEmbeddings",
    "StreamClassEngine",
    "StreamClassMember",
    "StreamProfile",
    "StreamProfiler",
    "StreamRepresentations",
    "StreamSemanticClass",
    "StreamSemanticPipeline",
    "StreamSemanticPipelineResult",
    "TemporalChange",
    "TemporalChangeType",
    "TemporalEntryState",
    "TemporalProfileUpdate",
    "TemporalStreamProfile",
    "TemporalStreamProfiler",
    "normalize_text",
]
