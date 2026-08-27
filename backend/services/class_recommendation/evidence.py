"""Registry for recommendation evidence definitions.

Evidence is declared in one place so representation rendering, matching, discovery,
prototype construction, API explanations, and the frontend can evolve without
hard-coding every evidence id in each layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from .profiling import FieldProfile

EvidenceId = str
EvidenceScope = Literal["pair", "stream"]
PairEvidenceRenderer = Callable[["FieldProfile"], str]


@dataclass(frozen=True, slots=True)
class EvidenceDefinition:
    evidence_id: EvidenceId
    label: str
    scope: EvidenceScope


@dataclass(frozen=True, slots=True)
class PairEvidenceSpec:
    definition: EvidenceDefinition
    renderer: PairEvidenceRenderer

    @property
    def evidence_id(self) -> EvidenceId:
        return self.definition.evidence_id


PAIR_EVIDENCE_SPECS: tuple[PairEvidenceSpec, ...] = (
    PairEvidenceSpec(
        EvidenceDefinition("key", "Similar keys", "pair"),
        lambda entry: entry.normalized_key,
    ),
    PairEvidenceSpec(
        EvidenceDefinition("value", "Similar values", "pair"),
        lambda entry: entry.normalized_value,
    ),
    PairEvidenceSpec(
        EvidenceDefinition("key_value", "Similar key + value meaning", "pair"),
        lambda entry: f"{entry.normalized_key}: {entry.normalized_value}",
    ),
    PairEvidenceSpec(
        EvidenceDefinition("schema", "Similar structure", "pair"),
        lambda entry: f"{entry.normalized_key}: {entry.value_type}",
    ),
)

STREAM_EVIDENCE_DEFINITIONS: tuple[EvidenceDefinition, ...] = (
    EvidenceDefinition(
        "stream_context",
        "Similar whole-stream context",
        "stream",
    ),
)

PAIR_EVIDENCE_IDS: tuple[EvidenceId, ...] = tuple(
    spec.evidence_id for spec in PAIR_EVIDENCE_SPECS
)
STREAM_EVIDENCE_IDS: tuple[EvidenceId, ...] = tuple(
    definition.evidence_id for definition in STREAM_EVIDENCE_DEFINITIONS
)
DISCOVERY_EVIDENCE_IDS: tuple[EvidenceId, ...] = (
    *PAIR_EVIDENCE_IDS,
    *STREAM_EVIDENCE_IDS,
)
EVIDENCE_CATALOG: tuple[EvidenceDefinition, ...] = (
    *(spec.definition for spec in PAIR_EVIDENCE_SPECS),
    *STREAM_EVIDENCE_DEFINITIONS,
)
EVIDENCE_BY_ID = {definition.evidence_id: definition for definition in EVIDENCE_CATALOG}


def evidence_definition(evidence_id: EvidenceId) -> EvidenceDefinition:
    try:
        return EVIDENCE_BY_ID[evidence_id]
    except KeyError as exc:
        raise ValueError(f"Unknown recommendation evidence id: {evidence_id}") from exc


def render_pair_evidence(entry: "FieldProfile") -> tuple[tuple[EvidenceId, str], ...]:
    return tuple((spec.evidence_id, spec.renderer(entry)) for spec in PAIR_EVIDENCE_SPECS)
