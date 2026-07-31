"""Deterministic structural profiling and textual representations for SmartMQTT streams."""

from .multi_view_consensus import (
    MultiViewConsensusEngine,
    MultiViewConsensusResult,
    RepresentationClassConsensus,
    RepresentationViewWinner,
)
from .pipeline import StreamSemanticPipeline, StreamSemanticPipelineResult
from .representation_class_scoring import (
    RepresentationClassCentroids,
    RepresentationClassEvidence,
    RepresentationClassEvidenceMatrix,
    RepresentationClassScorer,
    RepresentationClassScores,
)
from .representation_embedder import RepresentationEmbedder, RepresentationEmbeddings
from .representations import RepresentationBuilder, StreamRepresentations
from .semantic_class_decision import (
    SemanticClassDecision,
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionReason,
    SemanticClassDecisionState,
)
from .semantic_refresh import (
    SemanticRefreshDecision,
    SemanticRefreshPolicy,
    SemanticRefreshReason,
    SemanticRefreshReasonType,
)
from .stability_aware_representations import StabilityAwareRepresentationBuilder
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
    "MultiViewConsensusEngine",
    "MultiViewConsensusResult",
    "RepresentationBuilder",
    "RepresentationClassCentroids",
    "RepresentationClassConsensus",
    "RepresentationClassEvidence",
    "RepresentationClassEvidenceMatrix",
    "RepresentationClassScorer",
    "RepresentationClassScores",
    "RepresentationEmbedder",
    "RepresentationEmbeddings",
    "RepresentationViewWinner",
    "SemanticClassDecision",
    "SemanticClassDecisionConfig",
    "SemanticClassDecisionPolicy",
    "SemanticClassDecisionReason",
    "SemanticClassDecisionState",
    "SemanticRefreshDecision",
    "SemanticRefreshPolicy",
    "SemanticRefreshReason",
    "SemanticRefreshReasonType",
    "StabilityAwareRepresentationBuilder",
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
