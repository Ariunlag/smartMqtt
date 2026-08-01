"""Diagnostic HTTP surface for human semantic candidate review."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from models.semantic_review_models import (
    CandidateIdentityModel,
    NegativeMembershipConstraintList,
    PendingSemanticCandidateModel,
    SemanticMembershipReviewRequest,
    SemanticReviewResult,
    SemanticReviewState,
)
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
)
from services.semantic.semantic_review_runtime import (
    PendingCandidateNotFoundError,
    SemanticReviewRuntime,
)

router = APIRouter(prefix="/semantic-review", tags=["Semantic review"])
# TODO(semantic composition): replace this diagnostic singleton at the production
# composition root. That root must inject shared UnknownStreamPool,
# TrustedClassEvidenceStore, and NegativeMembershipConstraintStore instances into
# the processing and review runtimes as applicable, rather than creating a second
# independent production state path.
_runtime = SemanticReviewRuntime()


def get_semantic_review_runtime() -> SemanticReviewRuntime:
    """Return the default in-memory runtime; tests may override this dependency."""
    return _runtime


@router.get("/candidates", response_model=SemanticReviewState)
def list_candidates(
    runtime: Annotated[SemanticReviewRuntime, Depends(get_semantic_review_runtime)],
) -> SemanticReviewState:
    return SemanticReviewState(
        candidates=tuple(
            PendingSemanticCandidateModel(
                representation_name=candidate.identity.representation_name,
                member_topics=candidate.identity.member_topics,
                candidate_index=candidate.candidate_index,
            )
            for candidate in runtime.list_candidates()
        ),
        available_unknown_topics=runtime.list_unknown_topics(),
    )


@router.post("/reviews", response_model=SemanticReviewResult)
def apply_review(
    request: SemanticMembershipReviewRequest,
    runtime: Annotated[SemanticReviewRuntime, Depends(get_semantic_review_runtime)],
) -> SemanticReviewResult:
    try:
        identity = _identity(request.identity)
        review = CandidateMembershipReview(
            identity=identity,
            semantic_class_name=request.semantic_class_name,
            kept_topics=request.kept_topics,
            removed_topics=request.removed_topics,
            added_topics=request.added_topics,
            source=CandidateConfirmationSource.HUMAN,
        )
        result = runtime.apply_review(review)
    except PendingCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    workflow = result.workflow
    return SemanticReviewResult(
        semantic_class_name=workflow.semantic_class_name,
        positive_topics=workflow.positive_topics,
        removed_topics=workflow.removed_topics,
        changed_representations=workflow.changed_representations,
        constraints_added=workflow.constraints_added,
        constraints_removed=workflow.constraints_removed,
        prototypes=result.prototypes,
    )


@router.get("/constraints", response_model=NegativeMembershipConstraintList)
def list_constraints(
    runtime: Annotated[SemanticReviewRuntime, Depends(get_semantic_review_runtime)],
) -> NegativeMembershipConstraintList:
    return NegativeMembershipConstraintList(
        constraints=runtime.constraint_store.all(),
    )


def _identity(model: CandidateIdentityModel) -> CandidateIdentity:
    return CandidateIdentity(
        representation_name=model.representation_name,
        member_topics=model.member_topics,
    )
