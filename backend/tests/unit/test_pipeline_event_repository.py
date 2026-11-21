import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.repository.pipeline_event_repository as event_repo
import app.repository.scene_repository as scene_repo
from app.db.base import Base
from app.db.models import PipelineEvent


@pytest.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(scene_repo, "AsyncSessionLocal", factory)
    monkeypatch.setattr(event_repo, "AsyncSessionLocal", factory)

    yield factory

    await engine.dispose()


async def _events(factory) -> list[PipelineEvent]:
    async with factory() as session:
        return list((await session.execute(select(PipelineEvent))).scalars())


async def test_records_event_resolving_video_from_scene(session_factory):
    scene = await scene_repo.create_scene("prompt")

    await event_repo.record_event(
        node_name="codegen", status="ok", scene_id=scene.id,
        model_used="nvidia/nemotron-3-ultra-550b-a55b:free", tokens_in=10, tokens_out=20, latency_ms=5,
    )

    events = await _events(session_factory)
    assert len(events) == 1
    event = events[0]
    assert str(event.scene_id) == scene.id
    assert event.video_id is not None
    assert event.model_used == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert (event.tokens_in, event.tokens_out, event.latency_ms) == (10, 20, 5)


async def test_skips_when_no_ids(session_factory):
    await event_repo.record_event(node_name="codegen", status="ok")
    assert await _events(session_factory) == []


async def test_skips_unknown_scene(session_factory):
    await event_repo.record_event(node_name="codegen", status="ok", scene_id=str(uuid.uuid4()))
    assert await _events(session_factory) == []


async def test_db_failure_does_not_raise(monkeypatch):
    def broken_factory():
        raise RuntimeError("db down")

    monkeypatch.setattr(event_repo, "AsyncSessionLocal", broken_factory)
    await event_repo.record_event(node_name="codegen", status="ok", scene_id=str(uuid.uuid4()))
