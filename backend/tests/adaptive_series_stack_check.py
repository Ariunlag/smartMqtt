"""Acceptance helper: creates/deletes ONLY its own Influx bucket."""
import time
import uuid
from types import SimpleNamespace
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from config import config
from services.class_recommendation.adaptive import AdaptiveRecommendations
from services.class_recommendation.adaptive_series import InfluxSeriesSource, SeriesShapeProvider


def check_series(svc):
    end = int(time.time() // 60) * 60
    provider = SeriesShapeProvider(active=True, clock=lambda: end)
    svc.registry.register(provider)
    svc.series_provider = provider
    bucket_name = "smartmqtt-adaptive-test-" + uuid.uuid4().hex[:12]
    with InfluxDBClient(url=config.INFLUX_URL, token=config.INFLUX_TOKEN, org=config.INFLUX_ORG) as influx:
        buckets = influx.buckets_api()
        bucket = buckets.create_bucket(bucket_name=bucket_name, org=config.INFLUX_ORG)
        try:
            points = []
            for topic in ("lab/a", "lab/b", "lab/c"):
                for i in range(32):
                    value = float(i if topic == "lab/a" else 3*i+5 if topic == "lab/b" else -i)
                    points.append(Point(topic).tag("sensor_type", "temperature").tag("location", "lab")
                                  .field("reading", value).field("status", "ok")
                                  .time(datetime.fromtimestamp(end-32*60+i*60+5, timezone.utc)))
            with influx.write_api(write_options=SYNCHRONOUS) as writer:
                writer.write(bucket=bucket_name, record=points)
            svc.series_source = InfluxSeriesSource(SimpleNamespace(query_api=influx.query_api()), bucket_name)
            before = svc._load()
            assert svc.refresh_series()
            material = svc._load()
            assert material["lab/a"]["topic_text"] == before["lab/a"]["topic_text"]
            assert provider.compare(material["lab/a"]["series_shape"], material["lab/b"]["series_shape"])["score"] > .999
            assert provider.compare(material["lab/a"]["series_shape"], material["lab/c"]["series_shape"])["score"] < .001
            assert not svc.refresh_series()
            restarted = AdaptiveRecommendations(svc.encoder.model, svc.identity_store, store=svc.store,
                environment_id=svc.environment_id, series_provider=SeriesShapeProvider(active=True, clock=lambda: end))
            assert restarted._load()["lab/a"]["series_shape"] == material["lab/a"]["series_shape"]
            print("PASS: real Influx numeric filtering/UTC aggregation, shape model, PostgreSQL restart persistence")
        finally:
            assert bucket.name == bucket_name and bucket_name.startswith("smartmqtt-adaptive-test-")
            buckets.delete_bucket(bucket.id)
            print("Removed only the disposable time-series acceptance bucket")
