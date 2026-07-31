"""Frozen-config execution over REFERENCE and TEST benchmark streams only."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from services.embedding.base_model import BaseEmbeddingModel

from ..semantic_class_decision import SemanticClassDecisionConfig
from .benchmark import SemanticBenchmarkDataset, SemanticBenchmarkScenario
from .calibration import SemanticCalibrationSplit
from .experiment import (
    SemanticExperimentResult,
    SemanticExperimentRunner,
    SemanticExperimentVariant,
)


@dataclass(frozen=True, slots=True)
class FrozenSemanticBenchmarkConfig:
    decision_config: SemanticClassDecisionConfig


@dataclass(frozen=True, slots=True)
class SemanticBenchmarkRun:
    variant: SemanticExperimentVariant
    result: SemanticExperimentResult


@dataclass(frozen=True, slots=True)
class SemanticBenchmarkComparison:
    frozen_config: FrozenSemanticBenchmarkConfig
    runs: tuple[SemanticBenchmarkRun, ...]
    reference_stream_count: int
    test_stream_count: int
    known_class_names: tuple[str, ...]
    unseen_class_names: tuple[str, ...]

    def summary_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "variant": run.variant.value,
                "top1_accuracy": run.result.metrics.top1_accuracy,
                "macro_f1": run.result.metrics.macro_f1,
                "unknown_precision": run.result.metrics.unknown_precision,
                "unknown_recall": run.result.metrics.unknown_recall,
                "false_unknown_rate": run.result.metrics.false_unknown_rate,
                "semantic_refresh_count": run.result.metrics.semantic_refresh_count,
                "false_refresh_count": run.result.metrics.false_refresh_count,
            }
            for run in self.runs
        )


class SemanticBenchmarkExecutor:
    """Execute fixed variants without calibration, tuning, or discovery."""

    def execute(
        self,
        dataset: SemanticBenchmarkDataset,
        config: FrozenSemanticBenchmarkConfig,
        embedding_model: BaseEmbeddingModel,
    ) -> SemanticBenchmarkComparison:
        runner = SemanticExperimentRunner()
        reference = self._view(dataset, SemanticCalibrationSplit.REFERENCE)
        test = self._view(dataset, SemanticCalibrationSplit.TEST)
        runs = []
        for variant in SemanticExperimentVariant:
            classes = runner._reference_classes(reference, embedding_model, variant)
            decision_config = (
                config.decision_config
                if variant is SemanticExperimentVariant.OPEN_WORLD_MULTI_VIEW
                else None
            )
            predictions, refreshes, false_refreshes = runner._predict(
                test, variant, embedding_model, classes, decision_config
            )
            runs.append(
                SemanticBenchmarkRun(
                    variant,
                    SemanticExperimentResult(
                        variant,
                        predictions,
                        runner._metrics(predictions, refreshes, false_refreshes),
                    ),
                )
            )
        return SemanticBenchmarkComparison(
            config,
            tuple(runs),
            len(dataset.reference_streams),
            len(dataset.test_streams),
            dataset.known_class_names,
            dataset.unseen_class_names,
        )

    @staticmethod
    def _view(dataset, split):
        scenarios = tuple(
            SemanticBenchmarkScenario(
                item.scenario_id,
                item.scenario_type,
                item.expected_change,
                tuple(stream for stream in item.streams if stream.split is split),
            )
            for item in dataset.scenarios
            if any(stream.split is split for stream in item.streams)
        )
        return SimpleNamespace(
            known_class_names=dataset.known_class_names,
            unseen_class_names=dataset.unseen_class_names,
            scenarios=scenarios,
        )
