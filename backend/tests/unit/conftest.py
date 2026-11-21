import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 — registers tables on Base.metadata
from app.db.base import Base


@pytest.fixture
def fake_redis(monkeypatch):
    """Replace the app's Redis factory with in-memory fakeredis clients that
    all share one server — like separate processes sharing one real Redis."""
    server = fakeredis.FakeServer()

    def factory():
        return fakeredis.FakeAsyncRedis(server=server, decode_responses=True)

    monkeypatch.setattr("app.core.redis_client.get_redis", factory)
    return factory


# Repositories run against a real in-memory SQLite database rather than mocks:
# faking SQLAlchemy's query layer is more fragile than a throwaway schema, and
# no external service is involved.

_ASYNC_REPOS = (
    "app.repository.video_repository",
    "app.repository.scene_repository",
    "app.repository.pipeline_event_repository",
)
_SYNC_REPOS = (
    "app.repository.sync_video_repository",
    "app.repository.sync_scene_repository",
)


@pytest.fixture
async def db(monkeypatch):
    """Async session factory on a fresh schema, patched into every async repository."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    for module in _ASYNC_REPOS:
        monkeypatch.setattr(f"{module}.AsyncSessionLocal", factory)

    yield factory

    await engine.dispose()


@pytest.fixture
def sync_db(monkeypatch):
    """Sync session factory on a fresh schema, patched into the sync repositories."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in _SYNC_REPOS:
        monkeypatch.setattr(f"{module}.SessionLocal", factory)

    yield factory

    engine.dispose()
