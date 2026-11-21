"""Moving a video to its next stage.

advance(): compare-and-set status `from_stage → next_stage`, then enqueue a
run_stage task for the new stage. If the compare-and-set loses (someone else
already advanced), nothing is enqueued — so a stage is never queued twice.
If the enqueue fails (Redis down), the video is marked FAILED with
current_stage = the new stage, so POST /videos/{id}/resume can retry it.
"""
import asyncio
from typing import Optional

from app.core import activity
from app.core.logging import get_logger
from app.pipeline.dispatch import enqueue_stage
from app.pipeline.stages import next_stage
from app.repository.sync_video_repository import get_video_sync, transition_video_status_sync
from app.repository.video_repository import transition_video_status
from app.schemas.status import SceneStatus, VideoStatus

logger = get_logger(__name__)


class QueueUnavailable(RuntimeError):
    """The Celery broker could not accept the task."""


async def advance(video_id, from_stage: VideoStatus) -> Optional[VideoStatus]:
    """Advance and enqueue. Returns the new stage, or None if the video was
    no longer at from_stage. Raises QueueUnavailable."""
    to_stage = next_stage(from_stage)
    if not await transition_video_status(video_id, from_stage, to_stage):
        return None
    if to_stage != VideoStatus.COMPLETED:
        try:
            await asyncio.to_thread(enqueue_stage, video_id, to_stage)
        except Exception as e:
            await transition_video_status(
                video_id, to_stage, VideoStatus.FAILED, error_message=f"Queue dispatch failed: {e}"
            )
            activity.emit("video_failed", video_id=video_id, stage=to_stage.value, error=f"Queue dispatch failed: {e}")
            raise QueueUnavailable(str(e)) from e
    _announce(video_id, from_stage, to_stage)
    return to_stage


def _announce(video_id, from_stage: VideoStatus, to_stage: VideoStatus) -> None:
    if to_stage == VideoStatus.COMPLETED:
        activity.emit("video_completed", video_id=video_id)
    else:
        activity.emit("stage_queued", video_id=video_id, stage=to_stage.value, after=from_stage.value)


async def start(video_id) -> Optional[VideoStatus]:
    """Kick off a freshly CREATED video."""
    return await advance(video_id, VideoStatus.CREATED)


def advance_sync(video_id, from_stage: VideoStatus) -> Optional[VideoStatus]:
    """Sync twin of advance(), for Celery tasks that are not async."""
    to_stage = next_stage(from_stage)
    if not transition_video_status_sync(video_id, from_stage, to_stage):
        return None
    if to_stage != VideoStatus.COMPLETED:
        try:
            enqueue_stage(video_id, to_stage)
        except Exception as e:
            transition_video_status_sync(
                video_id, to_stage, VideoStatus.FAILED, error_message=f"Queue dispatch failed: {e}"
            )
            activity.emit("video_failed", video_id=video_id, stage=to_stage.value, error=f"Queue dispatch failed: {e}")
            raise QueueUnavailable(str(e)) from e
    _announce(video_id, from_stage, to_stage)
    return to_stage


def scene_render_finished_sync(video_id) -> None:
    """Fan-in for FINAL_RENDER, called by each render task after it saved its
    scene's result. The last scene to finish advances the video; any failed
    scene fails it. Each caller reads after its own commit, so the last one
    always sees every result, and the compare-and-set lets only one advance."""
    video = get_video_sync(video_id)
    if video is None or video.status != VideoStatus.FINAL_RENDER:
        return
    failed = [s for s in video.scenes if s.status == SceneStatus.FAILED]
    if failed:
        error = f"Scene {failed[0].order} render failed: {failed[0].error_message}"
        if transition_video_status_sync(
            video_id, VideoStatus.FINAL_RENDER, VideoStatus.FAILED, error_message=error
        ):
            activity.emit("video_failed", video_id=video_id, stage=VideoStatus.FINAL_RENDER.value, error=error)
    elif all(s.status == SceneStatus.RENDERED for s in video.scenes):
        advance_sync(video_id, VideoStatus.FINAL_RENDER)
