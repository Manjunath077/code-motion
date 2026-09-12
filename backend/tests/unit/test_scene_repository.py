import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.repository.scene_repository as repo
from app.db.base import Base
from app.db import models  # noqa: F401 — registers tables on Base.metadata
from app.schemas.scene_schema import SceneStatus

# These tests run against a real (in-memory) SQLite database rather than mocks,
# since faking SQLAlchemy's query layer convincingly is more fragile than just
# exercising the repository against a throwaway schema — no external service
# involved, so this still satisfies "unit: no external dependencies".


@pytest.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(repo, "AsyncSessionLocal", factory)

    yield factory

    await engine.dispose()


# ── create_scene ──────────────────────────────────────────────────────────────

async def test_create_scene_returns_scene_document(session_factory):
    scene = await repo.create_scene("test prompt")

    assert scene.prompt == "test prompt"
    assert scene.status == SceneStatus.PENDING
    assert scene.generated_script is None
    uuid.UUID(scene.id)  # doesn't raise


# ── get_scene_by_id ───────────────────────────────────────────────────────────

async def test_get_scene_by_id_found(session_factory):
    created = await repo.create_scene("test prompt")

    fetched = await repo.get_scene_by_id(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.prompt == "test prompt"


async def test_get_scene_by_id_not_found_returns_none(session_factory):
    scene = await repo.get_scene_by_id(str(uuid.uuid4()))
    assert scene is None


async def test_get_scene_by_id_invalid_id_returns_none(session_factory):
    scene = await repo.get_scene_by_id("not-a-valid-uuid")
    assert scene is None


# ── update_scene_status ───────────────────────────────────────────────────────

async def test_update_scene_status_updates_status(session_factory):
    created = await repo.create_scene("test prompt")

    await repo.update_scene_status(created.id, SceneStatus.COMPLETED)

    fetched = await repo.get_scene_by_id(created.id)
    assert fetched.status == SceneStatus.COMPLETED


async def test_update_scene_status_with_error_message(session_factory):
    created = await repo.create_scene("test prompt")

    await repo.update_scene_status(created.id, SceneStatus.FAILED, error_message="boom")

    fetched = await repo.get_scene_by_id(created.id)
    assert fetched.status == SceneStatus.FAILED
    assert fetched.error_message == "boom"


async def test_update_scene_status_unknown_id_is_a_noop(session_factory):
    # Should not raise even though nothing exists with this id.
    await repo.update_scene_status(str(uuid.uuid4()), SceneStatus.FAILED, error_message="boom")


# ── update_scene_script / update_scene_video ─────────────────────────────────

async def test_update_scene_script_persists_script(session_factory):
    created = await repo.create_scene("test prompt")

    await repo.update_scene_script(created.id, "from manim import *")

    fetched = await repo.get_scene_by_id(created.id)
    assert fetched.generated_script == "from manim import *"


async def test_update_scene_video_persists_video_url(session_factory):
    created = await repo.create_scene("test prompt")

    await repo.update_scene_video(created.id, "/media/abc/output.mp4")

    fetched = await repo.get_scene_by_id(created.id)
    assert fetched.video_url == "/media/abc/output.mp4"


# ── delete_scene ──────────────────────────────────────────────────────────────

async def test_delete_scene_returns_true_when_deleted(session_factory):
    created = await repo.create_scene("test prompt")

    result = await repo.delete_scene(created.id)

    assert result is True
    assert await repo.get_scene_by_id(created.id) is None


async def test_delete_scene_returns_false_when_not_found(session_factory):
    result = await repo.delete_scene(str(uuid.uuid4()))
    assert result is False


async def test_delete_scene_invalid_id_returns_false(session_factory):
    result = await repo.delete_scene("bad-id")
    assert result is False


# ── list_scenes ───────────────────────────────────────────────────────────────

async def test_list_scenes_returns_list_and_total(session_factory):
    await repo.create_scene("first")
    await repo.create_scene("second")

    scenes, total = await repo.list_scenes(limit=20, skip=0)

    assert len(scenes) == 2
    assert total == 2


async def test_list_scenes_empty(session_factory):
    scenes, total = await repo.list_scenes()
    assert scenes == []
    assert total == 0


async def test_list_scenes_respects_limit(session_factory):
    for i in range(3):
        await repo.create_scene(f"prompt {i}")

    scenes, total = await repo.list_scenes(limit=2, skip=0)

    assert len(scenes) == 2
    assert total == 3
