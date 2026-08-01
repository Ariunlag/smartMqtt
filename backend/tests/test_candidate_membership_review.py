from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    CandidateConfirmationSource,
    CandidateIdentity,
    CandidateMembershipReview,
    CandidateMembershipReviewProcessor,
    MembershipFeedbackKind,
    MembershipFeedbackPolarity,
    MembershipFeedbackStore,
)


def _review(**changes):
    values = {
        "identity": CandidateIdentity("key_value", ("topic/c", "topic/a", "topic/b")),
        "semantic_class_name": "Temperature Sensor",
        "kept_topics": ("topic/c", "topic/a"),
        "removed_topics": ("topic/b",),
        "added_topics": ("topic/d",),
        "source": CandidateConfirmationSource.HUMAN,
    }
    values.update(changes)
    return CandidateMembershipReview(**values)


def test_valid_review_is_canonical_and_exposes_diagnostics():
    review = _review()

    assert review.original_topics == ("topic/a", "topic/b", "topic/c")
    assert review.kept_topics == ("topic/a", "topic/c")
    assert review.removed_topics == ("topic/b",)
    assert review.added_topics == ("topic/d",)
    assert review.positive_topics == ("topic/a", "topic/c", "topic/d")
    assert review.negative_topics == ("topic/b",)
    assert (
        review.suggested_count,
        review.kept_count,
        review.removed_count,
        review.added_count,
        review.final_positive_count,
    ) == (3, 2, 1, 1, 3)
    assert review.suggestion_precision == pytest.approx(2 / 3)
    assert review.suggestion_coverage_proxy == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"kept_topics": ("topic/a",), "removed_topics": ("topic/b",)}, "partition"),
        (
            {
                "kept_topics": ("topic/a", "topic/b"),
                "removed_topics": ("topic/b", "topic/c"),
            },
            "disjoint",
        ),
        ({"added_topics": ("topic/a",)}, "added topics"),
        ({"kept_topics": ("topic/a", "topic/a")}, "duplicates"),
        ({"removed_topics": ("topic/b", "topic/b")}, "duplicates"),
        ({"added_topics": ("topic/d", "topic/d")}, "duplicates"),
        ({"added_topics": ("",)}, "non-empty"),
        ({"added_topics": (1,)}, "non-empty"),
        ({"semantic_class_name": " "}, "semantic_class_name"),
        (
            {
                "kept_topics": (),
                "removed_topics": ("topic/a", "topic/b", "topic/c"),
                "added_topics": (),
            },
            "positive",
        ),
    ),
)
def test_invalid_reviews_are_rejected(changes, message):
    with pytest.raises((TypeError, ValueError), match=message):
        _review(**changes)


def test_processor_maps_kinds_polarities_and_order_without_mutation():
    review = _review()
    identity = review.identity
    store = MembershipFeedbackStore()

    evidence = CandidateMembershipReviewProcessor().process(review, store)

    assert [(item.topic, item.kind, item.polarity) for item in evidence] == [
        ("topic/a", MembershipFeedbackKind.KEPT, MembershipFeedbackPolarity.POSITIVE),
        ("topic/c", MembershipFeedbackKind.KEPT, MembershipFeedbackPolarity.POSITIVE),
        ("topic/d", MembershipFeedbackKind.ADDED, MembershipFeedbackPolarity.POSITIVE),
        (
            "topic/b",
            MembershipFeedbackKind.REMOVED,
            MembershipFeedbackPolarity.NEGATIVE,
        ),
    ]
    assert all(item.representation_name == "key_value" for item in evidence)
    assert review == _review()
    assert review.identity is identity
    assert identity.member_topics == ("topic/a", "topic/b", "topic/c")


def test_store_replay_replaces_latest_state_and_remove_works():
    store = MembershipFeedbackStore()
    processor = CandidateMembershipReviewProcessor()
    first = _review(
        kept_topics=("topic/a", "topic/c"), removed_topics=("topic/b",), added_topics=()
    )
    processor.process(first, store)
    size = len(store)
    processor.process(first, store)
    assert len(store) == size

    later = _review(
        kept_topics=("topic/a", "topic/b", "topic/c"),
        removed_topics=(),
        added_topics=(),
    )
    processor.process(later, store)
    current = store.get("topic/b", "Temperature Sensor", "key_value")
    assert current.polarity is MembershipFeedbackPolarity.POSITIVE
    assert current.kind is MembershipFeedbackKind.KEPT
    assert store.remove("topic/b", "Temperature Sensor", "key_value") is current
    assert store.get("topic/b", "Temperature Sensor", "key_value") is None


def test_store_keeps_class_and_representation_contexts_separate_and_sorted():
    store = MembershipFeedbackStore()
    processor = CandidateMembershipReviewProcessor()
    processor.process(_review(), store)
    processor.process(_review(semantic_class_name="Air Quality"), store)
    processor.process(
        _review(
            identity=CandidateIdentity("schema", ("topic/a", "topic/b", "topic/c"))
        ),
        store,
    )

    all_evidence = store.all()
    assert isinstance(all_evidence, tuple)
    assert len(store) == 12
    assert [
        (item.semantic_class_name, item.representation_name, item.topic)
        for item in all_evidence
    ] == sorted(
        (item.semantic_class_name, item.representation_name, item.topic)
        for item in all_evidence
    )


def test_models_are_immutable_and_have_no_score_or_centroid_fields():
    review = _review()
    evidence = CandidateMembershipReviewProcessor().process(
        review, MembershipFeedbackStore()
    )[0]

    with pytest.raises(FrozenInstanceError):
        review.semantic_class_name = "other"
    with pytest.raises(FrozenInstanceError):
        evidence.polarity = MembershipFeedbackPolarity.NEGATIVE
    forbidden = {"similarity", "score", "centroid", "weight", "reliability"}
    assert forbidden.isdisjoint(review.__dataclass_fields__)
    assert forbidden.isdisjoint(evidence.__dataclass_fields__)
