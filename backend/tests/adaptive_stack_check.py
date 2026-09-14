"""Real PostgreSQL acceptance in a NEW disposable database; never reset an existing DB.

Run from backend: python tests/adaptive_stack_check.py
Requires a PostgreSQL role allowed to create databases. Uses the configured host/role,
creates a unique test database and deletes only that database after verification.
"""

import json
import os
import sys
import uuid
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config as AlembicConfig
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import URL
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import config
from services.class_recommendation.adaptive import AdaptiveRecommendations
from services.class_recommendation.adaptive_store import AdaptiveStore
from services.database.postgres import PostgresClient
from services.store.canonical_identity_store import CanonicalIdentityStore


class Model:
    def encode(self, texts):
        return [[1., 0., 0.] for _ in texts]


def serve_ui(svc):
    """Optional browser acceptance: actual API/DB with explicit synthetic evidence."""
    import uvicorn
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from api import classes, recommendations

    for i in range(12):
        svc.materialize(f"lab/long-building-name/floor-one/temperature-sensor-{i:02d}",
                        {"sensor_type": "temperature", "location": "lab"})
    app = FastAPI()
    app.state.class_recommendation = SimpleNamespace(adaptive=svc)
    app.include_router(classes.router, prefix="/api")
    app.include_router(recommendations.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"MQTTClient": True, "InfluxClient": True}

    @app.get("/api/topics")
    @app.get("/api/measurements")
    def topics():
        return {"topics": []}

    @app.get("/api/duplicates")
    def duplicates():
        return {"duplicates": []}

    @app.websocket("/ws")
    async def websocket(socket: WebSocket):
        await socket.accept()
        try:
            while True:
                raw = await socket.receive_text()
                if json.loads(raw).get("type") == "ping":
                    await socket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass

    app.mount("/", StaticFiles(directory="/ui", html=True), name="ui")
    print("Synthetic UI acceptance ready; stop the container to clean up its test database", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8000)


def main():
    params = conninfo_to_dict(config.POSTGRES_DSN)
    database_name = "smartmqtt_adaptive_test_" + uuid.uuid4().hex[:12]
    created = False
    client = None
    original_dsn = os.environ.get("POSTGRES_DSN")
    try:
        with psycopg.connect(config.POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
            created = True
        params["dbname"] = database_name
        client = PostgresClient(make_conninfo(**params))
        url = URL.create("postgresql+psycopg", username=params.get("user"), password=params.get("password"),
                         host=params.get("host"), port=int(params.get("port", 5432)), database=database_name)
        os.environ["POSTGRES_DSN"] = url.render_as_string(hide_password=False)
        alembic = AlembicConfig(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        alembic.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        command.upgrade(alembic, "head")
        command.upgrade(alembic, "head")
        print("PASS: clean migration and repeat upgrade")
        identity = CanonicalIdentityStore(client)
        store = AdaptiveStore("test-environment-a", client)
        svc = AdaptiveRecommendations(Model(), identity, store=store, environment_id="test-environment-a")
        for topic in ("lab/a", "lab/b", "lab/c"):
            svc.materialize(topic, {"sensor_type": "temperature", "location": "lab"})
        rows = client.fetch_all("SELECT topic, count(*) AS vectors FROM adaptive_evidence GROUP BY topic")
        assert len(rows) == 3 and all(r["vectors"] == 7 for r in rows), rows
        group = svc.recommendations()["groups"][0]
        removed = svc.edit(group["group_id"], "remove", group["revision"], topic="lab/b")
        assert "lab/b" not in removed["members"]
        restored = svc.edit(group["group_id"], "undo", removed["revision"])
        assert "lab/b" in restored["members"]
        saved = svc.edit(group["group_id"], "save", restored["revision"], name="Lab sensors")
        assert store.classes()[0]["topics"] == saved["members"]
        svc.manual_class("Manual", ["lab/a", "lab/c"])
        svc.manual_class("Manual", ["lab/a"], update=True)
        restarted = AdaptiveRecommendations(Model(), identity, store=AdaptiveStore("test-environment-a", client),
                                            environment_id="test-environment-a")
        cards = restarted.recommendations()["groups"]
        assert any(c["saved_class"] == "Lab sensors" for c in cards)
        assert any(c["saved_class"] == "Manual" and c["members"] == ["lab/a"] for c in cards)
        other = AdaptiveStore("test-environment-b", client)
        assert not other.topics() and not other.events() and not other.classes()
        print("PASS: vector persistence, remove/undo, saved/manual Classes, restart, environment isolation")
        svc.delete_class("Manual")
        svc.recommendations()
        assert not any(c["name"] == "Manual" for c in store.classes())
        # Non-384 vectors are supported by the evidence table without coercion.
        client.execute("""INSERT INTO adaptive_evidence(environment_id,topic,provider_id,provider_version,
                         entity,embedding,payload) VALUES (%s,%s,%s,%s,%s,%s::vector,%s::jsonb)""",
                       ("test-environment-a", "lab/a", "future", "1", "window", "[1,0,0,0,0]", json.dumps({"window": 1})))
        assert len(store.material()["lab/a"]["future"][0]["embedding"]) == 5
        from adaptive_series_stack_check import check_series
        check_series(svc)
        if "--serve-ui" in sys.argv:
            serve_ui(svc)
        client.disconnect()
        command.downgrade(alembic, "base")
        command.upgrade(alembic, "head")
        print("PASS: mixed dimensions, downgrade and re-upgrade")
    finally:
        if client:
            client.disconnect()
        if original_dsn is None:
            os.environ.pop("POSTGRES_DSN", None)
        else:
            os.environ["POSTGRES_DSN"] = original_dsn
        if created:
            assert database_name.startswith("smartmqtt_adaptive_test_")
            with psycopg.connect(config.POSTGRES_DSN, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))
            print("Removed only the disposable acceptance database")


if __name__ == "__main__":
    main()
