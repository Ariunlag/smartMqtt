import numpy as np
import pytest

from services.class_recommendation.adaptive_discovery import DiscoveryConfig, discover
from services.class_recommendation.adaptive_evidence import ProviderRegistry, TextProvider
from services.class_recommendation.adaptive_series import SeriesConfig, SeriesShapeProvider, InfluxSeriesSource
from test_adaptive_recommendations import service, seed


def materials(n=80):
    registry = ProviderRegistry([TextProvider("topic_text", "Topic", "stream")])
    rng = np.random.default_rng(42)
    centers = np.eye(8)
    data = {f"topic-{i:04d}": {"topic_text": [{"embedding": (centers[i % 8] + rng.normal(0, .025, 8)).tolist(),
                "payload": {"text": str(i)}}]} for i in range(n)}
    return registry, data


def test_approximate_discovery_has_bounded_pairs_determinism_and_no_chain_merges():
    registry, data = materials(160)
    config = DiscoveryConfig(exact_limit=0, neighbors=12, projections=6, window=6, max_group_size=10)
    groups, metrics, _, scores = discover(data, registry, {"topic_text": 1.}, .9, config)
    again = discover(data, registry, {"topic_text": 1.}, .9, config)
    assert groups == again[0] and scores == again[3]
    assert metrics["scored_pairs"] <= len(data) * config.neighbors
    assert metrics["scored_pairs"] < metrics["possible_pairs"] / 3
    topics = sorted(data)
    for group in groups:
        assert len(group) <= 10
        assert len({int(t.split("-")[1]) % 8 for t in group}) == 1
        for a in group:
            for b in group:
                if a < b:
                    assert scores[(topics.index(a), topics.index(b))] > .9


def test_exact_path_and_approximate_retrieval_recall_on_separated_clusters():
    registry, data = materials(64)
    exact = discover(data, registry, {"topic_text": 1.}, .9, DiscoveryConfig())
    approximate = discover(data, registry, {"topic_text": 1.}, .9, DiscoveryConfig(exact_limit=0, neighbors=16))
    assert sorted(map(sorted, exact[0])) == sorted(map(sorted, approximate[0]))
    assert exact[1]["mode"] == "exact"
    assert exact[1]["scored_pairs"] == 64 * 63 // 2


def test_empty_and_singleton_discovery_are_valid_and_have_fresh_metrics():
    registry, data = materials(1)
    for rows in ({}, data):
        groups, metrics, neighbors, scores = discover(rows, registry, {"topic_text": 1.}, .8, DiscoveryConfig())
        assert not groups and not scores
        assert metrics["topic_count"] == len(rows) and metrics["scored_pairs"] == 0


def test_large_manual_groups_bound_reference_work_without_self_similarity():
    svc = service()
    refs = [f"topic-{i}" for i in range(1000)]
    assert len(svc._references("topic-1", refs)) == 32
    assert "topic-1" not in svc._references("topic-1", refs)
    assert svc._references("topic-1", refs) == svc._references("topic-1", list(reversed(refs)))


def series_provider():
    return SeriesShapeProvider(SeriesConfig(step_seconds=1, bins=32, min_points=16), active=True, clock=lambda: 1000)


def window(provider, values, *, field="reading", tags=None, end=1000):
    tags = tags or {"unit": "C"}
    points = [{"field": field, "value": value, "time": end - len(values) + i, "tags": tags}
              for i, value in enumerate(values) if value is not None]
    return provider.window_records("sensor", tags, points, end)


def test_shape_is_affine_invariant_signed_and_never_joins_distinct_tags():
    provider = series_provider()
    signal = np.sin(np.linspace(0, 7, 32))
    a = window(provider, signal.tolist())
    b = window(provider, (signal * 20 + 300).tolist(), tags={"unit": "F"})
    assert provider.compare(a, b)["score"] == pytest.approx(1.)
    assert provider.compare(a, window(provider, (-signal).tolist()))["score"] == pytest.approx(0.)
    assert provider.window_records("sensor", {"unit": "C"},
        [{"field": "reading", "value": 2., "time": 999, "tags": {"unit": "F"}}], 1000) == []


def test_series_missing_constant_stale_overlap_and_windows_are_masked():
    provider = series_provider()
    full = window(provider, list(range(32)))
    sparse = window(provider, [None] * 20 + list(range(12)))
    assert provider.compare(full, sparse)["score"] is None
    assert provider.compare(full, window(provider, [1.] * 32))["score"] is None
    assert provider.compare(full, window(provider, list(range(32)), end=990))["status"] == "stale"
    assert provider.retrieval_records(window(provider, list(range(32)), end=990)) == []
    assert provider.compare(full, window(provider, list(range(32)), end=999))["score"] is None
    half = window(provider, [None] * 16 + list(range(16)))
    assert provider.compare(full, half)["coverage"] == .5
    assert provider.compare(full, half)["score"] == pytest.approx(1.)


def test_numeric_fields_boolean_and_nonfinite_values_and_future_points_are_ignored():
    provider = series_provider()
    points = [{"field": "v", "value": v, "time": t, "tags": {}}
              for v, t in [(True, 999), (float("nan"), 999), (2., 1000), (3., 900)]]
    assert provider.window_records("sensor", {}, points, 1000) == []


def test_series_refresh_uses_persisted_source_and_does_not_reembed_text():
    svc = service()
    seed(svc)
    provider = series_provider()
    svc.registry.register(provider)
    svc.series_provider = provider
    class Source:
        calls = 0
        def fetch(self, topics, end, config):
            self.calls += 1
            return {topic: [{"field": "reading", "time": 968+i, "value": float(i),
                            "tags": svc.store.rows[topic]["tags"]} for i in range(32)] for topic in topics}
    def replace_provider(topic, expected, key, version, records):
        if svc.store.topic_fingerprint(topic) != expected:
            return False
        svc.store.vectors[topic][key] = [{**r, "provider_version": version} for r in records]
        return True
    svc.store.replace_provider = replace_provider
    svc.series_source = Source()
    calls = len(svc.encoder.model.calls)
    assert svc.refresh_series()
    assert not svc.refresh_series()
    assert svc.series_source.calls == 1
    assert len(svc.encoder.model.calls) == calls
    assert svc._evidence("a", ["b"], svc._load())["series_shape"]["score"] == pytest.approx(1.)


def test_flux_reader_escapes_topics_and_uses_closed_windows_and_numeric_filter():
    class Query:
        def query_stream(self, flux):
            self.flux = flux
            return iter([])
    query = Query()
    from types import SimpleNamespace
    source = InfluxSeriesSource(SimpleNamespace(query_api=query), "bucket")
    source.fetch(['bad"${topic}'], 1000, SeriesConfig(step_seconds=1))
    assert 'bad\\"\\${topic}' in query.flux
    assert 'types.isNumeric' in query.flux and 'timeSrc: "_start"' in query.flux
    assert 'createEmpty: false' in query.flux
