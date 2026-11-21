import fakeredis
import pytest


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace the app's Redis factory with in-memory fakeredis clients that
    all share one server — like separate processes sharing one real Redis."""
    server = fakeredis.FakeServer()

    def factory():
        return fakeredis.FakeAsyncRedis(server=server, decode_responses=True)

    monkeypatch.setattr("app.core.redis_client.get_redis", factory)
    return factory
