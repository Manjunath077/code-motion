import uuid

import pytest

import app.repository.scene_repository as scene_repo
import app.repository.video_repository as repo
from app.schemas.artifacts import Domain, Spec
from app.schemas.status import SceneStatus, VideoStatus


# ── create / get ──────────────────────────────────────────────────────────────

async def test_create_video_defaults(db):
    video = await repo.create_video("explain heap sort")

    assert video.user_prompt == "explain heap sort"
    assert video.status == VideoStatus.CREATED
    assert video.current_stage == VideoStatus.CREATED
    assert video.review_mode is True
    assert video.storyboard_version == 0
    assert video.scenes == []


async def test_create_video_review_mode_off(db):
    video = await repo.create_video("p", review_mode=False)
    assert video.review_mode is False


async def test_get_video_includes_scenes_in_order(db):
    video = await repo.create_video("p")
    await scene_repo.create_scene(video.id, order=1)
    await scene_repo.create_scene(video.id, order=0)

    fetched = await repo.get_video(video.id)

    assert [s.order for s in fetched.scenes] == [0, 1]


@pytest.mark.parametrize("bad_id", [str(uuid.uuid4()), "not-a-uuid", None])
async def test_get_video_missing_returns_none(db, bad_id):
    assert await repo.get_video(bad_id) is None


# ── list ──────────────────────────────────────────────────────────────────────

async def test_list_videos_total_and_limit(db):
    for i in range(3):
        await repo.create_video(f"p{i}")

    videos, total = await repo.list_videos(limit=2)

    assert len(videos) == 2
    assert total == 3


async def test_list_videos_empty(db):
    assert await repo.list_videos() == ([], 0)


# ── status ────────────────────────────────────────────────────────────────────

async def test_status_advances_current_stage(db):
    video = await repo.create_video("p")

    await repo.update_video_status(video.id, VideoStatus.OUTLINE)

    fetched = await repo.get_video(video.id)
    assert fetched.status == VideoStatus.OUTLINE
    assert fetched.current_stage == VideoStatus.OUTLINE


@pytest.mark.parametrize("halt", [VideoStatus.FAILED, VideoStatus.WAITING_QUOTA])
async def test_halt_status_keeps_current_stage(db, halt):
    video = await repo.create_video("p")
    await repo.update_video_status(video.id, VideoStatus.STORYBOARD)

    await repo.update_video_status(video.id, halt, error_message="stopped")

    fetched = await repo.get_video(video.id)
    assert fetched.status == halt
    assert fetched.current_stage == VideoStatus.STORYBOARD
    assert fetched.error_message == "stopped"


async def test_video_status_does_not_touch_scenes(db):
    video = await repo.create_video("p")
    scene = await scene_repo.create_scene(video.id)

    await repo.update_video_status(video.id, VideoStatus.FAILED)

    assert (await scene_repo.get_scene(scene.id)).status == SceneStatus.PENDING


async def test_update_status_unknown_id_returns_false(db):
    assert await repo.update_video_status(uuid.uuid4(), VideoStatus.FAILED) is False


async def test_invalid_status_value_raises(db):
    video = await repo.create_video("p")
    with pytest.raises(ValueError):
        await repo.update_video_status(video.id, "rendering")


# ── fields ────────────────────────────────────────────────────────────────────

async def test_update_video_stores_artifact_as_json(db):
    video = await repo.create_video("p")
    spec = Spec(
        topic="Heap Sort", domain=Domain.ALGORITHM, audience="CS undergrad",
        duration_s=300, words_budget=750, learning_goals=["max-heap property"],
    )

    assert await repo.update_video(video.id, spec=spec, title="Heap Sort") is True

    fetched = await repo.get_video(video.id)
    assert fetched.spec == spec
    assert fetched.title == "Heap Sort"


async def test_update_video_rejects_unknown_and_status_fields(db):
    video = await repo.create_video("p")
    with pytest.raises(ValueError):
        await repo.update_video(video.id, status="completed")
    with pytest.raises(ValueError):
        await repo.update_video(video.id, no_such_column=1)


# ── delete ────────────────────────────────────────────────────────────────────

async def test_delete_video_cascades_to_scenes(db):
    video = await repo.create_video("p")
    scene = await scene_repo.create_scene(video.id)

    assert await repo.delete_video(video.id) is True

    assert await repo.get_video(video.id) is None
    assert await scene_repo.get_scene(scene.id) is None


@pytest.mark.parametrize("bad_id", [str(uuid.uuid4()), "bad-id"])
async def test_delete_video_missing_returns_false(db, bad_id):
    assert await repo.delete_video(bad_id) is False
