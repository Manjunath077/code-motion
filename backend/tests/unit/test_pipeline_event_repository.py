import uuid

from sqlalchemy import select

import app.repository.pipeline_event_repository as event_repo
import app.repository.scene_repository as scene_repo
import app.repository.video_repository as video_repo
from app.db.models import PipelineEvent


async def _events(factory) -> list[PipelineEvent]:
    async with factory() as session:
        return list((await session.execute(select(PipelineEvent))).scalars())


async def test_records_event_resolving_video_from_scene(db):
    video = await video_repo.create_video("prompt")
    scene = await scene_repo.create_scene(video.id)

    await event_repo.record_event(
        node_name="codegen", status="ok", scene_id=scene.id,
        model_used="nvidia/nemotron-3-ultra-550b-a55b:free", tokens_in=10, tokens_out=20, latency_ms=5,
    )

    events = await _events(db)
    assert len(events) == 1
    event = events[0]
    assert event.scene_id == scene.id
    assert event.video_id == video.id
    assert event.model_used == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert (event.tokens_in, event.tokens_out, event.latency_ms) == (10, 20, 5)


async def test_skips_when_no_ids(db):
    await event_repo.record_event(node_name="codegen", status="ok")
    assert await _events(db) == []


async def test_skips_unknown_scene(db):
    await event_repo.record_event(node_name="codegen", status="ok", scene_id=str(uuid.uuid4()))
    assert await _events(db) == []


async def test_db_failure_does_not_raise(monkeypatch):
    def broken_factory():
        raise RuntimeError("db down")

    monkeypatch.setattr(event_repo, "AsyncSessionLocal", broken_factory)
    await event_repo.record_event(node_name="codegen", status="ok", scene_id=str(uuid.uuid4()))
