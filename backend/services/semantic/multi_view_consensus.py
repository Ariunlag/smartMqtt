"""Equal-view consensus evidence for representation-specific class scores."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real

from .representation_class_scoring import (
    RepresentationClassEvidence,
    RepresentationClassEvidenceMatrix,
)

_REPRESENTATION_NAMES = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


@dataclass(frozen=True, slots=True)
class RepresentationViewWinner:
    """The deterministic top-ranked class for one representation view."""

    representation_name: str
    class_id: str
    class_name: str
    similarity: float


@dataclass(frozen=True, slots=True)
class RepresentationClassConsensus:
    """Equal-view descriptive consensus evidence for one known class."""

    class_id: str
    class_name: str
    top1_votes: int
    mean_rank: float
    mean_similarity: float


@dataclass(frozen=True, slots=True)
class MultiViewConsensusResult:
    """View winners and deterministically ranked class consensus rows."""

    view_winners: tuple[RepresentationViewWinner, ...]
    classes: tuple[RepresentationClassConsensus, ...]

    @property
    def top_candidate(self) -> RepresentationClassConsensus | None:
        """Return the highest-ranked candidate without assigning a class."""
        return self.classes[0] if self.classes else None


class MultiViewConsensusEngine:
    """Derive an unweighted six-view consensus baseline from raw evidence."""

    @classmethod
    def build(
        cls,
        evidence: RepresentationClassEvidenceMatrix,
    ) -> MultiViewConsensusResult:
        """Summarize equal-view ranks, winners, votes, and similarities."""
        rows = tuple(evidence.rows)
        cls._validate_rows(rows)
        if not rows:
            return MultiViewConsensusResult(view_winners=(), classes=())

        rankings = {
            name: tuple(
                sorted(
                    rows,
                    key=lambda row: (-getattr(row.scores, name), row.class_id),
                )
            )
            for name in _REPRESENTATION_NAMES
        }
        view_winners = tuple(
            cls._view_winner(name, rankings[name][0]) for name in _REPRESENTATION_NAMES
        )
        votes = {row.class_id: 0 for row in rows}
        for winner in view_winners:
            votes[winner.class_id] += 1

        ranks = {
            name: {
                row.class_id: rank for rank, row in enumerate(rankings[name], start=1)
            }
            for name in _REPRESENTATION_NAMES
        }
        summaries = [
            RepresentationClassConsensus(
                class_id=row.class_id,
                class_name=row.class_name,
                top1_votes=votes[row.class_id],
                mean_rank=math.fsum(
                    ranks[name][row.class_id] for name in _REPRESENTATION_NAMES
                )
                / len(_REPRESENTATION_NAMES),
                mean_similarity=math.fsum(
                    getattr(row.scores, name) for name in _REPRESENTATION_NAMES
                )
                / len(_REPRESENTATION_NAMES),
            )
            for row in rows
        ]
        summaries.sort(
            key=lambda summary: (
                -summary.top1_votes,
                summary.mean_rank,
                -summary.mean_similarity,
                summary.class_id,
            )
        )
        return MultiViewConsensusResult(
            view_winners=view_winners,
            classes=tuple(summaries),
        )

    @staticmethod
    def _view_winner(
        representation_name: str,
        row: RepresentationClassEvidence,
    ) -> RepresentationViewWinner:
        return RepresentationViewWinner(
            representation_name=representation_name,
            class_id=row.class_id,
            class_name=row.class_name,
            similarity=getattr(row.scores, representation_name),
        )

    @staticmethod
    def _validate_rows(rows: tuple[RepresentationClassEvidence, ...]) -> None:
        seen: set[str] = set()
        for row in rows:
            if row.class_id in seen:
                raise ValueError(f"Duplicate class_id: '{row.class_id}'")
            seen.add(row.class_id)

            for name in _REPRESENTATION_NAMES:
                value = getattr(row.scores, name)
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise TypeError(
                        f"Score for class '{row.class_id}', representation "
                        f"'{name}' must be numeric and finite"
                    )
                if not math.isfinite(value):
                    raise ValueError(
                        f"Score for class '{row.class_id}', representation "
                        f"'{name}' must be numeric and finite"
                    )
