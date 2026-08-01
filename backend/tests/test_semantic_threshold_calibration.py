import pytest
from services.semantic import MultiViewConsensusResult, RepresentationClassConsensus
from services.semantic.evaluation import (
    SemanticCalibrationEvidence,
    SemanticDecisionThresholdGrid,
    SemanticThresholdCalibrator,
)


def _evidence(unseen=False):
    return SemanticCalibrationEvidence(
        "Unseen" if unseen else "Known",
        unseen,
        MultiViewConsensusResult(
            (),
            (RepresentationClassConsensus("known", "Known", 6, 1.0, 0.9),),
        ),
    )


def test_grid_and_calibration_are_deterministic_and_calibration_only():
    grid = SemanticDecisionThresholdGrid((1, 7), (0.5,), (0.0,), (0.2,))
    evidence = (_evidence(), _evidence(True))

    result = SemanticThresholdCalibrator().calibrate(evidence, grid)

    assert len(result.all_candidates) == 1
    assert result == SemanticThresholdCalibrator().calibrate(evidence, grid)
    assert result.all_candidates[0].metrics.known_count == 1
    assert result.all_candidates[0].metrics.unseen_count == 1


def test_test_split_evidence_is_rejected():
    from services.semantic.evaluation import SemanticCalibrationSplit

    with pytest.raises(ValueError, match="CALIBRATION"):
        SemanticCalibrationEvidence(
            "Known",
            False,
            MultiViewConsensusResult((), ()),
            SemanticCalibrationSplit.TEST,
        )
