import uuid

import pytest

import app.repository.scene_repository as repo
import app.repository.video_repository as video_repo
from app.schemas.artifacts import SceneBeat, Storyboard, Zone
from app.schemas.status import SceneStatus, VideoStatus


@pytest.fixture
async def video(db):
    return await video_repo.create_video("explain heap sort")


# ── create / get ──────────────────────────────────────────────────────────────

async def test_create_scene_defaults(video):
    scene = await repo.create_scene(video.id, order=2)

    assert scene.video_id == video.id
    assert scene.order == 2
    assert scene.status == SceneStatus.PENDING
    assert scene.generated_script is None


async def test_create_scene_unknown_video_returns_none(db):
    assert await repo.create_scene(uuid.uuid4()) is None


async def test_get_scene_found(video):
    created = await repo.create_scene(video.id)

    fetched = await repo.get_scene(str(created.id))

    assert fetched.id == created.id


@pytest.mark.parametrize("bad_id", [str(uuid.uuid4()), "not-a-valid-uuid"])
async def test_get_scene_missing_returns_none(db, bad_id):
    assert await repo.get_scene(bad_id) is None


# ── list ──────────────────────────────────────────────────────────────────────

async def test_list_scenes_of_one_video_in_order(video):
    other = await video_repo.create_video("other")
    await repo.create_scene(video.id, order=1)
    await repo.create_scene(video.id, order=0)
    await repo.create_scene(other.id)

    scenes, total = await repo.list_scenes(video.id)

    assert [s.order for s in scenes] == [0, 1]
    assert total == 2


async def test_list_all_scenes_respects_limit(video):
    for i in range(3):
        await repo.create_scene(video.id, order=i)

    scenes, total = await repo.list_scenes(limit=2)

    assert len(scenes) == 2
    assert total == 3


async def test_list_scenes_empty(db):
    assert await repo.list_scenes() == ([], 0)


# ── status: decoupled from the video ──────────────────────────────────────────

async def test_scene_status_does_not_change_video_status(video):
    """The old repository overwrote video.status on every scene update."""
    scene = await repo.create_scene(video.id)
    await video_repo.update_video_status(video.id, VideoStatus.QA)

    await repo.update_scene_status(scene.id, SceneStatus.FAILED, error_message="boom")

    fetched_scene = await repo.get_scene(scene.id)
    fetched_video = await video_repo.get_video(video.id)
    assert fetched_scene.status == SceneStatus.FAILED
    assert fetched_scene.error_message == "boom"
    assert fetched_video.status == VideoStatus.QA
    assert fetched_video.error_message is None


async def test_update_scene_status_with_fields(video):
    scene = await repo.create_scene(video.id)

    await repo.update_scene_status(
        scene.id, SceneStatus.RENDERED, rendered_segment_url="/media/v/scenes/s.mp4"
    )

    fetched = await repo.get_scene(scene.id)
    assert fetched.status == SceneStatus.RENDERED
    assert fetched.rendered_segment_url == "/media/v/scenes/s.mp4"


async def test_update_scene_status_unknown_id_returns_false(db):
    assert await repo.update_scene_status(str(uuid.uuid4()), SceneStatus.FAILED) is False


async def test_invalid_scene_status_raises(video):
    scene = await repo.create_scene(video.id)
    with pytest.raises(ValueError):
        await repo.update_scene_status(scene.id, "queued")


# ── fields ────────────────────────────────────────────────────────────────────

async def test_update_scene_stores_storyboard(video):
    scene = await repo.create_scene(video.id)
    storyboard = Storyboard(
        id="S4", duration_s=45,
        start_state="array top, tree bottom", end_state="node 4 settled at index 3",
        beats=[SceneBeat(narration="Compare it with both children.", visual="pulse children", trace_ref=[12])],
        layout={"array": Zone.TOP, "tree": Zone.CENTER},
    )

    await repo.update_scene(scene.id, storyboard=storyboard, generated_script="from manim import *")

    fetched = await repo.get_scene(scene.id)
    assert fetched.storyboard == storyboard
    assert fetched.generated_script == "from manim import *"


async def test_update_scene_rejects_unknown_fields(video):
    scene = await repo.create_scene(video.id)
    with pytest.raises(ValueError):
        await repo.update_scene(scene.id, status="rendered")


# ── delete ────────────────────────────────────────────────────────────────────

async def test_delete_scene_keeps_video(video):
    scene = await repo.create_scene(video.id)

    assert await repo.delete_scene(scene.id) is True

    assert await repo.get_scene(scene.id) is None
    assert await video_repo.get_video(video.id) is not None


@pytest.mark.parametrize("bad_id", [str(uuid.uuid4()), "bad-id"])
async def test_delete_scene_missing_returns_false(db, bad_id):
    assert await repo.delete_scene(bad_id) is False
