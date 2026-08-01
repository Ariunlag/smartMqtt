"""Diagnostic HTTP surface for human semantic candidate review."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from models.semantic_review_models import (
    CandidateIdentityModel,
    NegativeMembershipConstraintList,
    PendingSemanticCandidateModel,
    SemanticClassList,
    SemanticMembershipReviewRequest,
    SemanticReviewResult,
    SemanticReviewState,
)
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    SemanticApplication,
)
from services.semantic.semantic_review_runtime import (
    PendingCandidateNotFoundError,
    SemanticReviewRuntime,
)

router = APIRouter(prefix="/semantic-review", tags=["Semantic review"])


def get_semantic_application(request: Request) -> SemanticApplication:
    """Return the semantic composition attached to this FastAPI app instance."""
    application = getattr(request.app.state, "semantic_application", None)
    if application is None:
        raise HTTPException(
            status_code=503,
            detail="Semantic application is not initialized",
        )
    return application


def get_semantic_review_runtime(
    application: Annotated[SemanticApplication, Depends(get_semantic_application)],
) -> SemanticReviewRuntime:
    """Resolve review state from the application-level composition root."""
    return application.review_runtime


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
        result = runtime.apply_review(review, request.class_id)
    except PendingCandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    workflow = result.workflow
    return SemanticReviewResult(
        class_id=result.class_id,
        semantic_class_name=workflow.semantic_class_name,
        registry_updated=result.registry_updated,
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


@router.get("/classes", response_model=SemanticClassList)
def list_classes(
    application: Annotated[SemanticApplication, Depends(get_semantic_application)],
) -> SemanticClassList:
    return SemanticClassList(classes=application.class_catalog.all())


def _identity(model: CandidateIdentityModel) -> CandidateIdentity:
    return CandidateIdentity(
        representation_name=model.representation_name,
        member_topics=model.member_topics,
    )
