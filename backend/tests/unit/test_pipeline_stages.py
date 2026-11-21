"""Stage order and the interim stage handlers."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.pipeline.stages as stages
import app.repository.scene_repository as scene_repo
import app.repository.video_repository as video_repo
from app.pipeline.stages import Outcome, StageError, next_stage
from app.schemas.status import SceneStatus, VideoStatus
from app.utils.script_validator import ValidationResult

VALID = ValidationResult(is_valid=True, error="")
INVALID = ValidationResult(is_valid=False, error="banned import 'os'")


# ── order ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage, expected", [
    (VideoStatus.CREATED, VideoStatus.CODEGEN),        # SPEC … AWAITING_APPROVAL not built yet
    (VideoStatus.CODEGEN, VideoStatus.FINAL_RENDER),   # QA, TTS not built yet
    (VideoStatus.FINAL_RENDER, VideoStatus.ASSEMBLE),
    (VideoStatus.ASSEMBLE, VideoStatus.COMPLETED),
    (VideoStatus.SPEC, VideoStatus.CODEGEN),           # resumed at a skipped stage
])
def test_next_stage_skips_stages_without_handler(stage, expected):
    assert next_stage(stage) == expected


@pytest.mark.parametrize("stage", [VideoStatus.FAILED, VideoStatus.WAITING_QUOTA, VideoStatus.COMPLETED])
def test_next_stage_of_non_pipeline_or_last_raises(stage):
    with pytest.raises(ValueError):
        next_stage(stage)


# ── codegen ───────────────────────────────────────────────────────────────────

@pytest.fixture
def llm(monkeypatch):
    m = {
        "generate": AsyncMock(return_value="script-0"),
        "fix": AsyncMock(side_effect=["script-1", "script-2"]),
        "validate": MagicMock(return_value=VALID),
    }
    monkeypatch.setattr(stages, "generate_manim_script", m["generate"])
    monkeypatch.setattr(stages, "fix_manim_script", m["fix"])
    monkeypatch.setattr(stages, "validate_manim_script", m["validate"])
    return m


async def _video(**kwargs):
    v = await video_repo.create_video("explain heap sort", **kwargs)
    return v


async def test_codegen_creates_scene_and_approves_valid_script(db, llm):
    video = await _video()

    assert await stages.codegen(video) is Outcome.NEXT

    (scene,) = (await video_repo.get_video(video.id)).scenes
    assert scene.status == SceneStatus.APPROVED
    assert scene.generated_script == "script-0"
    llm["fix"].assert_not_awaited()
    llm["generate"].assert_awaited_once_with("explain heap sort", scene_id=str(scene.id))


async def test_codegen_rerun_reuses_existing_scene(db, llm):
    video = await _video()
    await stages.codegen(video)

    await stages.codegen(await video_repo.get_video(video.id))

    assert len((await video_repo.get_video(video.id)).scenes) == 1


async def test_codegen_one_repair_then_valid(db, llm):
    llm["validate"].side_effect = [INVALID, VALID]
    video = await _video()

    await stages.codegen(video)

    assert llm["fix"].await_count == 1
    (scene,) = (await video_repo.get_video(video.id)).scenes
    assert scene.generated_script == "script-1"


async def test_codegen_gives_up_after_two_repairs(db, llm):
    llm["validate"].return_value = INVALID
    video = await _video()

    with pytest.raises(StageError, match="banned import"):
        await stages.codegen(video)

    assert llm["fix"].await_count == 2
    (scene,) = (await video_repo.get_video(video.id)).scenes
    assert scene.status == SceneStatus.FAILED


async def test_codegen_llm_error_fails_scene_and_reraises(db, llm):
    llm["generate"].side_effect = RuntimeError("OpenRouter down")
    video = await _video()

    with pytest.raises(RuntimeError):
        await stages.codegen(video)

    (scene,) = (await video_repo.get_video(video.id)).scenes
    assert scene.status == SceneStatus.FAILED
    assert scene.error_message == "OpenRouter down"


# ── final_render ──────────────────────────────────────────────────────────────

@pytest.fixture
def render_queue(monkeypatch):
    m = MagicMock()
    monkeypatch.setattr(stages, "enqueue_render", m)
    return m


async def test_final_render_queues_unrendered_scenes_and_waits(db, render_queue):
    video = await _video()
    done = await scene_repo.create_scene(video.id, order=0, generated_script="s")
    await scene_repo.update_scene_status(done.id, SceneStatus.RENDERED)
    todo = await scene_repo.create_scene(video.id, order=1, generated_script="s")

    assert await stages.final_render(await video_repo.get_video(video.id)) is Outcome.WAIT

    render_queue.assert_called_once_with(todo.id)
    assert (await scene_repo.get_scene(todo.id)).status == SceneStatus.APPROVED


async def test_final_render_all_rendered_moves_on(db, render_queue):
    video = await _video()
    scene = await scene_repo.create_scene(video.id, generated_script="s")
    await scene_repo.update_scene_status(scene.id, SceneStatus.RENDERED)

    assert await stages.final_render(await video_repo.get_video(video.id)) is Outcome.NEXT
    render_queue.assert_not_called()


async def test_final_render_without_scenes_or_script_fails(db, render_queue):
    video = await _video()
    with pytest.raises(StageError):
        await stages.final_render(video)

    await scene_repo.create_scene(video.id)
    with pytest.raises(StageError, match="no script"):
        await stages.final_render(await video_repo.get_video(video.id))
    render_queue.assert_not_called()


# ── assemble ──────────────────────────────────────────────────────────────────

async def test_assemble_single_scene_sets_final_url(db):
    video = await _video()
    scene = await scene_repo.create_scene(video.id)
    await scene_repo.update_scene_status(scene.id, SceneStatus.RENDERED, rendered_segment_url="/media/x.mp4")

    assert await stages.assemble(await video_repo.get_video(video.id)) is Outcome.NEXT

    assert (await video_repo.get_video(video.id)).final_video_url == "/media/x.mp4"


async def test_assemble_unrendered_scene_fails(db):
    video = await _video()
    await scene_repo.create_scene(video.id)
    with pytest.raises(StageError):
        await stages.assemble(await video_repo.get_video(video.id))
