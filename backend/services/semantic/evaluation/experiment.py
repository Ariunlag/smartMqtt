"""Deterministic benchmark experiments over existing semantic components."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from services.embedding.base_model import BaseEmbeddingModel

from ..multi_view_consensus import MultiViewConsensusEngine
from ..representation_class_scoring import (
    RepresentationClassCentroids,
    RepresentationClassScorer,
)
from ..representation_embedder import RepresentationEmbedder, RepresentationEmbeddings
from ..representations import RepresentationBuilder
from ..semantic_class_decision import (
    SemanticClassDecisionConfig,
    SemanticClassDecisionPolicy,
    SemanticClassDecisionState,
)
from ..semantic_refresh import SemanticRefreshPolicy
from ..stability_aware_representations import StabilityAwareRepresentationBuilder
from ..stream_class import StreamClassEngine
from ..stream_profiler import StreamProfiler
from ..temporal_profile import TemporalChangeType, TemporalStreamProfiler
from .benchmark import SemanticBenchmarkDataset, SemanticBenchmarkScenarioType


class SemanticExperimentVariant(str, Enum):
    SINGLE_VIEW_KEY_ONLY = "SINGLE_VIEW_KEY_ONLY"
    SINGLE_VIEW_SCHEMA = "SINGLE_VIEW_SCHEMA"
    STATIC_MULTI_VIEW = "STATIC_MULTI_VIEW"
    TEMPORAL_MULTI_VIEW = "TEMPORAL_MULTI_VIEW"
    OPEN_WORLD_MULTI_VIEW = "OPEN_WORLD_MULTI_VIEW"


@dataclass(frozen=True, slots=True)
class SemanticPrediction:
    scenario_id: str
    topic: str
    observation_index: int
    expected_class_name: str
    is_unseen_class: bool
    predicted_class_name: str | None
    decision_state: SemanticClassDecisionState | None


@dataclass(frozen=True, slots=True)
class SemanticExperimentMetrics:
    top1_accuracy: float
    macro_f1: float
    unknown_precision: float
    unknown_recall: float
    false_unknown_rate: float
    semantic_refresh_count: int
    false_refresh_count: int


@dataclass(frozen=True, slots=True)
class SemanticExperimentResult:
    variant: SemanticExperimentVariant
    predictions: tuple[SemanticPrediction, ...]
    metrics: SemanticExperimentMetrics


class SemanticExperimentRunner:
    """Run fixed benchmark variants without discovery, feedback, or persistence."""

    def run(
        self,
        dataset: SemanticBenchmarkDataset,
        variant: SemanticExperimentVariant,
        embedding_model: BaseEmbeddingModel,
        decision_config: SemanticClassDecisionConfig | None = None,
    ) -> SemanticExperimentResult:
        if (
            variant is SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW
            and decision_config is None
        ):
            raise ValueError("OPEN_WORLD_MULTI_VIEW requires decision_config")
        if not isinstance(variant, SemanticExperimentVariant):
            raise TypeError("variant must be a SemanticExperimentVariant")
        reference = self._reference_classes(dataset, embedding_model, variant)
        predictions, refreshes, false_refreshes = self._predict(
            dataset, variant, embedding_model, reference, decision_config
        )
        return SemanticExperimentResult(
            variant=variant,
            predictions=predictions,
            metrics=self._metrics(predictions, refreshes, false_refreshes),
        )

    def _reference_classes(self, dataset, model, variant):
        grouped = defaultdict(list)
        for scenario in dataset.scenarios:
            for stream in scenario.streams:
                if stream.expected_class_name in dataset.known_class_names:
                    grouped[stream.expected_class_name].append(stream.observations[0])
        embedder = RepresentationEmbedder(model)
        classes = []
        for name in dataset.known_class_names:
            vectors = [
                self._snapshot_embedding(embedder, item) for item in grouped[name]
            ]
            classes.append(
                RepresentationClassCentroids(
                    class_id=name,
                    class_name=name,
                    centroids=RepresentationEmbeddings(
                        **{
                            view: StreamClassEngine.compute_centroid(
                                getattr(vector, view) for vector in vectors
                            )
                            for view in _VIEWS
                        }
                    ),
                )
            )
        return tuple(classes)

    def _predict(self, dataset, variant, model, classes, config):
        embedder = RepresentationEmbedder(model)
        predictions, refreshes, false_refreshes = [], 0, 0
        for scenario in dataset.scenarios:
            for stream in scenario.streams:
                temporal, profile = TemporalStreamProfiler(), None
                refresh_policy = SemanticRefreshPolicy()
                for observation in stream.observations:
                    if variant in _TEMPORAL:
                        update = temporal.update(
                            profile,
                            StreamProfiler().profile(
                                observation.topic, observation.tags, observation.fields
                            ),
                        )
                        profile = update.profile
                        refresh = refresh_policy.evaluate(update).should_refresh
                        refreshes += int(refresh)
                        false_refreshes += int(
                            refresh
                            and scenario.scenario_type
                            is SemanticBenchmarkScenarioType.BENIGN_NUMERIC_DRIFT
                            and update.changes
                            and all(
                                change.change_type is TemporalChangeType.VALUE_CHANGED
                                for change in update.changes
                            )
                        )
                        embeddings = embedder.embed(
                            StabilityAwareRepresentationBuilder().build(profile)
                        )
                    else:
                        embeddings = self._snapshot_embedding(embedder, observation)
                    state, predicted = self._classify(
                        embeddings, classes, variant, config
                    )
                    predictions.append(
                        SemanticPrediction(
                            scenario.scenario_id,
                            observation.topic,
                            observation.observation_index,
                            observation.expected_class_name,
                            observation.is_unseen_class,
                            predicted,
                            state,
                        )
                    )
        return tuple(predictions), refreshes, false_refreshes

    @staticmethod
    def _snapshot_embedding(embedder, observation):
        return embedder.embed(
            RepresentationBuilder().build(
                observation.topic, observation.tags, observation.fields
            )
        )

    @staticmethod
    def _classify(embeddings, classes, variant, config):
        evidence = RepresentationClassScorer.score(embeddings, classes)
        if variant is SemanticExperimentVariant.SINGLE_VIEW_KEY_ONLY:
            row = min(
                evidence.rows, key=lambda item: (-item.scores.key_only, item.class_id)
            )
            return None, row.class_name
        if variant is SemanticExperimentVariant.SINGLE_VIEW_SCHEMA:
            row = min(
                evidence.rows, key=lambda item: (-item.scores.schema, item.class_id)
            )
            return None, row.class_name
        consensus = MultiViewConsensusEngine.build(evidence)
        if variant is not SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW:
            return None, consensus.top_candidate.class_name
        decision = SemanticClassDecisionPolicy(config).decide(consensus)
        return (
            decision.state,
            decision.candidate.class_name
            if decision.state is SemanticClassDecisionState.KNOWN
            else None,
        )

    @staticmethod
    def _metrics(predictions, refreshes, false_refreshes):
        known = [item for item in predictions if not item.is_unseen_class]
        correct = sum(
            item.predicted_class_name == item.expected_class_name for item in known
        )
        unknown = [
            item
            for item in predictions
            if item.decision_state is SemanticClassDecisionState.UNKNOWN
        ]
        true_positive = sum(item.is_unseen_class for item in unknown)
        actual_unseen = sum(item.is_unseen_class for item in predictions)
        labels = sorted({item.expected_class_name for item in known})
        f1 = []
        for label in labels:
            tp = sum(
                item.expected_class_name == label and item.predicted_class_name == label
                for item in known
            )
            fp = sum(
                item.expected_class_name != label and item.predicted_class_name == label
                for item in known
            )
            fn = sum(
                item.expected_class_name == label and item.predicted_class_name != label
                for item in known
            )
            f1.append(0.0 if 2 * tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn))
        return SemanticExperimentMetrics(
            correct / len(known) if known else 0.0,
            sum(f1) / len(f1) if f1 else 0.0,
            true_positive / len(unknown) if unknown else 0.0,
            true_positive / actual_unseen if actual_unseen else 0.0,
            sum(not item.is_unseen_class for item in unknown) / len(known)
            if known
            else 0.0,
            refreshes,
            false_refreshes,
        )


_VIEWS = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)
_TEMPORAL = {
    SemanticExperimentVariant.TEMPORAL_MULTI_VIEW,
    SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW,
}
