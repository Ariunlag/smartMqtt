from dataclasses import FrozenInstanceError

import pytest
from services.semantic import (
    KnownClassAssembler,
    KnownClassAssemblyRequest,
    RepresentationClassCentroids,
    TrustedClassEvidence,
    TrustedClassEvidenceStore,
)

REPRESENTATIONS = (
    "value_only",
    "key_only",
    "key_value",
    "schema",
    "numeric_key_only",
    "topic_key_value",
)


def _evidence(
    representation_name: str,
    vector: tuple[float, ...],
    semantic_class_name: str = "temperature",
    topics: tuple[str, ...] = ("sensors/one",),
) -> TrustedClassEvidence:
    return TrustedClassEvidence(
        semantic_class_name=semantic_class_name,
        representation_name=representation_name,
        centroid=vector,
        member_topics=topics,
    )


def _complete_store(
    semantic_class_name: str = "temperature",
) -> TrustedClassEvidenceStore:
    store = TrustedClassEvidenceStore()
    for index, representation_name in enumerate(reversed(REPRESENTATIONS), start=1):
        store.upsert(
            _evidence(
                representation_name,
                (float(index), float(index * 10)),
                semantic_class_name,
                (f"sensors/{representation_name}",),
            )
        )
    return store


def _assemble(store: TrustedClassEvidenceStore):
    return KnownClassAssembler().assemble(
        KnownClassAssemblyRequest("class-temperature", "temperature"), store
    )


def test_empty_store_returns_all_views_missing_in_contract_order():
    result = _assemble(TrustedClassEvidenceStore())

    assert result.missing_representations == REPRESENTATIONS
    assert result.centroids is None
    assert not result.is_complete


def test_one_trusted_view_leaves_the_other_five_missing():
    store = TrustedClassEvidenceStore()
    store.upsert(_evidence("value_only", (1.0, 2.0)))

    result = _assemble(store)

    assert result.missing_representations == REPRESENTATIONS[1:]
    assert result.centroids is None


def test_five_trusted_views_remain_incomplete_without_partial_centroids():
    store = _complete_store()
    store.remove("temperature", "schema")

    result = _assemble(store)

    assert result.missing_representations == ("schema",)
    assert result.centroids is None


def test_all_views_assemble_exact_matching_centroids_without_fusion():
    store = _complete_store()

    result = _assemble(store)

    assert result.is_complete
    assert isinstance(result.centroids, RepresentationClassCentroids)
    assert result.centroids.class_id == "class-temperature"
    assert result.centroids.class_name == "temperature"
    for representation_name in REPRESENTATIONS:
        prototype = store.get("temperature", representation_name).prototype
        assert (
            getattr(result.centroids.centroids, representation_name)
            == prototype.centroid
        )


def test_each_view_remains_independent_and_is_not_weighted_by_topics():
    store = TrustedClassEvidenceStore()
    for index, representation_name in enumerate(REPRESENTATIONS, start=1):
        store.upsert(
            _evidence(
                representation_name,
                (float(index), float(index + 100)),
                topics=tuple(f"sensors/{index}/{topic}" for topic in range(index)),
            )
        )

    centroids = _assemble(store).centroids.centroids

    assert centroids.value_only == (1.0, 101.0)
    assert centroids.key_only == (2.0, 102.0)
    assert centroids.topic_key_value == (6.0, 106.0)
    assert len({getattr(centroids, name) for name in REPRESENTATIONS}) == 6


def test_another_class_cannot_fill_a_missing_requested_view():
    store = _complete_store()
    store.remove("temperature", "schema")
    store.upsert(_evidence("schema", (99.0, 99.0), "humidity"))

    result = _assemble(store)

    assert result.missing_representations == ("schema",)
    assert result.centroids is None


def test_class_names_assemble_independently():
    store = _complete_store("temperature")
    humidity = _complete_store("humidity")
    for item in humidity.all():
        store.upsert(item)

    result = KnownClassAssembler().assemble(
        KnownClassAssemblyRequest("class-humidity", "humidity"), store
    )

    assert result.is_complete
    assert result.centroids.class_id == "class-humidity"
    assert result.centroids.class_name == "humidity"


def test_assembly_is_deterministic_and_does_not_mutate_trusted_evidence():
    store = _complete_store()
    before = store.all()

    first = _assemble(store)
    second = _assemble(store)

    assert first == second
    assert store.all() == before
    assert all(
        store.get(item.semantic_class_name, item.representation_name) is item
        for item in before
    )


@pytest.mark.parametrize("class_id", ("", "   ", 1))
def test_invalid_class_id_is_rejected(class_id):
    with pytest.raises((TypeError, ValueError)):
        KnownClassAssemblyRequest(class_id, "temperature")


@pytest.mark.parametrize("semantic_class_name", ("", "   ", 1))
def test_invalid_semantic_class_name_is_rejected(semantic_class_name):
    with pytest.raises((TypeError, ValueError)):
        KnownClassAssemblyRequest("class-temperature", semantic_class_name)


def test_request_and_result_models_are_immutable():
    request = KnownClassAssemblyRequest("class-temperature", "temperature")
    result = _assemble(TrustedClassEvidenceStore())

    with pytest.raises(FrozenInstanceError):
        request.class_id = "other"
    with pytest.raises(FrozenInstanceError):
        result.centroids = None
