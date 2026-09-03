from contextlib import contextmanager

from services.database import postgres as postgres_module


class FakeCursor:
    def __init__(self, rows=None, row=None, rowcount=1):
        self._rows = rows or []
        self._row = row
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "SELECT 1" in sql:
            return FakeCursor(row={"ready": True})
        return FakeCursor(rows=[{"value": 1}], row={"value": 1})


class FakePool:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.connection_calls = 0
        self.closed = False
        self.conn = FakeConnection()
        type(self).instances.append(self)

    @contextmanager
    def connection(self, timeout=None):
        self.connection_calls += 1
        yield self.conn

    def close(self):
        self.closed = True


def test_postgres_client_reuses_one_pool_for_multiple_operations(monkeypatch):
    FakePool.instances.clear()
    monkeypatch.setattr(postgres_module, "ConnectionPool", FakePool)
    client = postgres_module.PostgresClient("postgresql://example")

    assert client.fetch_one("SELECT value") == {"value": 1}
    assert client.fetch_all("SELECT value") == [{"value": 1}]
    assert client.execute("UPDATE example SET value = 1") == 1

    assert len(FakePool.instances) == 1
    pool = FakePool.instances[0]
    assert pool.connection_calls == 3
    assert pool.kwargs["min_size"] == 0
    assert pool.kwargs["max_size"] >= 1

    client.disconnect()
    assert pool.closed is True


def test_postgres_client_recreates_pool_after_disconnect(monkeypatch):
    FakePool.instances.clear()
    monkeypatch.setattr(postgres_module, "ConnectionPool", FakePool)
    client = postgres_module.PostgresClient("postgresql://example")

    client.fetch_one("SELECT value")
    client.disconnect()
    client.fetch_one("SELECT value")

    assert len(FakePool.instances) == 2
