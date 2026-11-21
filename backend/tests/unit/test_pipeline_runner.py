"""State machine: advancing, stale tasks, failures, quota waits, resume."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

import app.pipeline.stages as stages
import app.repository.video_repository as video_repo
from app.core.quota import QuotaExhausted
from app.db.models import PipelineEvent
from app.pipeline import runner, transitions
from app.pipeline.stages import Outcome
from app.schemas.status import VideoStatus


@pytest.fixture
def queue(monkeypatch):
    """Every Celery send replaced by a mock."""
    m = {"stage": MagicMock(), "resume": MagicMock()}
    monkeypatch.setattr(transitions, "enqueue_stage", m["stage"])
    monkeypatch.setattr(runner, "enqueue_stage", m["stage"])
    monkeypatch.setattr(runner, "schedule_resume", m["resume"])
    return m


@pytest.fixture
def handler(monkeypatch):
    """Replace the CODEGEN handler with a mock."""
    m = AsyncMock(return_value=Outcome.NEXT)
    monkeypatch.setitem(stages.HANDLERS, VideoStatus.CODEGEN, m)
    return m


async def _at_codegen(queue):
    video = await video_repo.create_video("p")
    await transitions.start(video.id)
    queue["stage"].reset_mock()
    return video


async def _status(video_id):
    return await video_repo.get_video(video_id)


# ── start / advance ───────────────────────────────────────────────────────────

async def test_start_skips_to_first_built_stage_and_enqueues(db, queue):
    video = await video_repo.create_video("p")

    assert await transitions.start(video.id) == VideoStatus.CODEGEN

    fetched = await _status(video.id)
    assert fetched.status == VideoStatus.CODEGEN
    assert fetched.current_stage == VideoStatus.CODEGEN
    queue["stage"].assert_called_once_with(video.id, VideoStatus.CODEGEN)


async def test_advance_twice_from_same_stage_enqueues_once(db, queue):
    video = await video_repo.create_video("p")

    assert await transitions.advance(video.id, VideoStatus.CREATED) == VideoStatus.CODEGEN
    assert await transitions.advance(video.id, VideoStatus.CREATED) is None

    assert queue["stage"].call_count == 1


async def test_enqueue_failure_marks_failed_at_new_stage(db, queue):
    queue["stage"].side_effect = ConnectionError("redis down")
    video = await video_repo.create_video("p")

    with pytest.raises(transitions.QueueUnavailable):
        await transitions.start(video.id)

    fetched = await _status(video.id)
    assert fetched.status == VideoStatus.FAILED
    assert fetched.current_stage == VideoStatus.CODEGEN
    assert "redis down" in fetched.error_message


async def test_advance_to_completed_enqueues_nothing(db, queue, monkeypatch):
    video = await video_repo.create_video("p")
    await video_repo.update_video_status(video.id, VideoStatus.ASSEMBLE)

    assert await transitions.advance(video.id, VideoStatus.ASSEMBLE) == VideoStatus.COMPLETED
    queue["stage"].assert_not_called()


# ── run_stage ─────────────────────────────────────────────────────────────────

async def test_run_stage_runs_handler_and_advances(db, queue, handler):
    video = await _at_codegen(queue)

    await runner.run_stage(str(video.id), VideoStatus.CODEGEN)

    handler.assert_awaited_once()
    assert (await _status(video.id)).status == VideoStatus.FINAL_RENDER
    queue["stage"].assert_called_once_with(str(video.id), VideoStatus.FINAL_RENDER)


async def test_run_stage_wait_does_not_advance(db, queue, handler):
    handler.return_value = Outcome.WAIT
    video = await _at_codegen(queue)

    await runner.run_stage(str(video.id), VideoStatus.CODEGEN)

    assert (await _status(video.id)).status == VideoStatus.CODEGEN
    queue["stage"].assert_not_called()


async def test_stale_task_is_a_noop(db, queue, handler):
    video = await video_repo.create_video("p")  # still CREATED

    await runner.run_stage(str(video.id), VideoStatus.CODEGEN)

    handler.assert_not_awaited()
    assert (await _status(video.id)).status == VideoStatus.CREATED


async def test_missing_video_is_a_noop(db, queue, handler):
    import uuid
    await runner.run_stage(str(uuid.uuid4()), VideoStatus.CODEGEN)
    handler.assert_not_awaited()


async def test_handler_error_fails_video_keeping_stage(db, queue, handler):
    handler.side_effect = RuntimeError("boom")
    video = await _at_codegen(queue)

    await runner.run_stage(str(video.id), VideoStatus.CODEGEN)

    fetched = await _status(video.id)
    assert fetched.status == VideoStatus.FAILED
    assert fetched.current_stage == VideoStatus.CODEGEN
    assert fetched.error_message == "boom"
    queue["stage"].assert_not_called()


async def test_quota_exhausted_waits_and_schedules_retry(db, queue, handler):
    handler.side_effect = QuotaExhausted("12 free requests left")
    video = await _at_codegen(queue)

    await runner.run_stage(str(video.id), VideoStatus.CODEGEN)

    fetched = await _status(video.id)
    assert fetched.status == VideoStatus.WAITING_QUOTA
    assert fetched.current_stage == VideoStatus.CODEGEN
    queue["resume"].assert_called_once_with(str(video.id), 1800)


async def test_stage_events_recorded(db, queue, handler):
    video = await _at_codegen(queue)

    await runner.run_stage(str(video.id), VideoStatus.CODEGEN)

    async with db() as session:
        events = list((await session.execute(select(PipelineEvent))).scalars())
    assert [(e.node_name, e.status) for e in events] == [("stage:codegen", "ok")]
    assert events[0].video_id == video.id


# ── resume ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("halt", [VideoStatus.FAILED, VideoStatus.WAITING_QUOTA])
async def test_resume_restarts_current_stage(db, queue, halt):
    video = await _at_codegen(queue)
    await video_repo.update_video_status(video.id, halt, error_message="x")

    assert await runner.resume(str(video.id)) is True

    fetched = await _status(video.id)
    assert fetched.status == VideoStatus.CODEGEN
    assert fetched.error_message is None
    queue["stage"].assert_called_once_with(str(video.id), VideoStatus.CODEGEN)


async def test_resume_not_halted_returns_false(db, queue):
    video = await _at_codegen(queue)

    assert await runner.resume(str(video.id)) is False
    queue["stage"].assert_not_called()


async def test_resume_enqueue_failure_marks_failed_again(db, queue):
    video = await _at_codegen(queue)
    await video_repo.update_video_status(video.id, VideoStatus.FAILED)
    queue["stage"].side_effect = ConnectionError("redis down")

    with pytest.raises(transitions.QueueUnavailable):
        await runner.resume(str(video.id))

    fetched = await _status(video.id)
    assert fetched.status == VideoStatus.FAILED
    assert fetched.current_stage == VideoStatus.CODEGEN


async def test_full_interim_pipeline_with_real_handlers(db, queue, monkeypatch):
    """CREATED → CODEGEN → FINAL_RENDER (render 'finishes') → ASSEMBLE → COMPLETED."""
    import app.repository.scene_repository as scene_repo
    from app.schemas.status import SceneStatus
    from app.utils.script_validator import ValidationResult

    monkeypatch.setattr(stages, "generate_manim_script", AsyncMock(return_value="from manim import *"))
    monkeypatch.setattr(stages, "validate_manim_script", MagicMock(return_value=ValidationResult(is_valid=True, error="")))
    monkeypatch.setattr(stages, "enqueue_render", MagicMock())
    video = await video_repo.create_video("p")
    vid = str(video.id)

    await transitions.start(vid)
    await runner.run_stage(vid, VideoStatus.CODEGEN)
    await runner.run_stage(vid, VideoStatus.FINAL_RENDER)
    assert (await _status(vid)).status == VideoStatus.FINAL_RENDER  # waiting for the render

    (scene,) = (await _status(vid)).scenes
    await scene_repo.update_scene_status(scene.id, SceneStatus.RENDERED, rendered_segment_url="/media/s.mp4")
    await transitions.advance(vid, VideoStatus.FINAL_RENDER)  # what the render fan-in does
    await runner.run_stage(vid, VideoStatus.ASSEMBLE)

    fetched = await _status(vid)
    assert fetched.status == VideoStatus.COMPLETED
    assert fetched.final_video_url == "/media/s.mp4"


# ── stuck videos: kick / sweep ────────────────────────────────────────────────

async def _age(db, video_id, minutes: int):
    """Pretend the video row was last changed `minutes` ago."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.db.models import Video
    async with db() as session, session.begin():
        await session.execute(
            update(Video).where(Video.id == video_id)
            .values(updated_at=datetime.now(timezone.utc) - timedelta(minutes=minutes))
        )


async def test_sweep_requeues_stuck_video_once(db, queue, monkeypatch):
    monkeypatch.setattr(runner.settings, "PIPELINE_STALE_AFTER_S", 600)
    video = await _at_codegen(queue)
    await _age(db, video.id, 30)

    assert await runner.sweep_stale() == 1
    queue["stage"].assert_called_once_with(video.id, VideoStatus.CODEGEN)
    assert (await _status(video.id)).status == VideoStatus.CODEGEN

    # updated_at was bumped by the kick → not stuck again until another 10 min
    assert await runner.sweep_stale() == 0
    assert queue["stage"].call_count == 1


async def test_sweep_ignores_fresh_and_non_recoverable_videos(db, queue, monkeypatch):
    monkeypatch.setattr(runner.settings, "PIPELINE_STALE_AFTER_S", 600)
    fresh = await _at_codegen(queue)
    for status in (VideoStatus.FAILED, VideoStatus.COMPLETED, VideoStatus.AWAITING_APPROVAL):
        v = await video_repo.create_video("p")
        await video_repo.update_video_status(v.id, status)
        await _age(db, v.id, 30)

    assert await runner.sweep_stale() == 0
    queue["stage"].assert_not_called()
    assert (await _status(fresh.id)).status == VideoStatus.CODEGEN


async def test_sweep_resumes_stuck_waiting_quota(db, queue, monkeypatch):
    monkeypatch.setattr(runner.settings, "PIPELINE_STALE_AFTER_S", 600)
    video = await _at_codegen(queue)
    await video_repo.update_video_status(video.id, VideoStatus.WAITING_QUOTA)
    await _age(db, video.id, 30)

    assert await runner.sweep_stale() == 1
    assert (await _status(video.id)).status == VideoStatus.CODEGEN


async def test_sweep_kicks_stuck_created_video(db, queue, monkeypatch):
    """API died between creating the video and queueing it."""
    monkeypatch.setattr(runner.settings, "PIPELINE_STALE_AFTER_S", 600)
    video = await video_repo.create_video("p")
    await _age(db, video.id, 30)

    assert await runner.sweep_stale() == 1
    queue["stage"].assert_called_once_with(video.id, VideoStatus.CREATED)


async def test_is_stuck(db, queue, monkeypatch):
    monkeypatch.setattr(runner.settings, "PIPELINE_STALE_AFTER_S", 600)
    video = await _at_codegen(queue)
    assert runner.is_stuck(await _status(video.id)) is False
    await _age(db, video.id, 30)
    assert runner.is_stuck(await _status(video.id)) is True
