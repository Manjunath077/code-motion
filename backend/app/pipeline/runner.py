"""Run one stage of one video; resume a halted video; recover stuck ones.

Called from the Celery tasks in app/workers/pipeline_task.py. The video's
status is the stage it is in; a run_stage(video, stage) task only acts if
the video is still at that stage, so stale or duplicate tasks are no-ops.

Stuck videos: a task can be lost (worker running old code discards an
unknown task, broker data lost, API died between create and enqueue). A
video at a pipeline stage whose row has not changed for
PIPELINE_STALE_AFTER_S is re-queued by kick(), run every
PIPELINE_SWEEP_INTERVAL_S by Celery beat (sweep_stale) and on demand by
POST /videos/{id}/resume.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from app.core import activity
from app.core.config import settings
from app.core.logging import get_logger
from app.core.quota import QuotaExhausted
from app.pipeline.dispatch import enqueue_stage, schedule_resume
from app.pipeline.stages import HANDLERS, PIPELINE, Outcome
from app.pipeline.transitions import QueueUnavailable, advance
from app.repository.pipeline_event_repository import record_event
from app.repository.video_repository import get_video, list_stale_videos, transition_video_status
from app.schemas.api import VideoOut
from app.schemas.status import VIDEO_HALT_STATUSES, VideoStatus

logger = get_logger(__name__)

_MAX_ERROR_CHARS = 2000

# Statuses a worker should be actively moving. Not here: AWAITING_APPROVAL
# (waits for a person), COMPLETED, FAILED (needs a person to resume).
# WAITING_QUOTA is here because its scheduled retry task can be lost too.
RECOVERABLE_STATUSES = frozenset(
    s for s in PIPELINE if s not in (VideoStatus.AWAITING_APPROVAL, VideoStatus.COMPLETED)
) | {VideoStatus.WAITING_QUOTA}


async def run_stage(video_id: str, stage: VideoStatus) -> None:
    stage = VideoStatus(stage)
    video = await get_video(video_id)
    if video is None:
        logger.info("run_stage: video %s no longer exists", video_id)
        return
    if video.status != stage:
        logger.info(
            "run_stage: video %s is at %s, not %s — skipping stale task",
            video_id, video.status.value, stage.value,
        )
        return

    handler = HANDLERS.get(stage)
    if handler is None:  # CREATED, or a stage resumed before its step existed
        await _advance(video_id, stage)
        return

    started = time.monotonic()
    node = f"stage:{stage.value}"
    activity.emit("stage_started", video_id=video_id, stage=stage.value)
    try:
        outcome = await handler(video)
    except QuotaExhausted as e:
        await _event(video_id, node, "waiting_quota", started, {"error": str(e)})
        activity.emit(
            "waiting_quota", video_id=video_id, stage=stage.value,
            retry_in=f"{settings.PIPELINE_QUOTA_RETRY_S} s", reason=str(e),
        )
        if await transition_video_status(
            video_id, stage, VideoStatus.WAITING_QUOTA, error_message=str(e)[:_MAX_ERROR_CHARS]
        ):
            await asyncio.to_thread(schedule_resume, video_id, settings.PIPELINE_QUOTA_RETRY_S)
            logger.warning(
                "Video %s waiting for quota at %s; retry in %d s",
                video_id, stage.value, settings.PIPELINE_QUOTA_RETRY_S,
            )
        return
    except Exception as e:
        logger.exception("Video %s failed at stage %s", video_id, stage.value)
        message = str(e) or type(e).__name__
        await _event(video_id, node, "error", started, {"error": message[:500]})
        activity.emit(
            "stage_failed", video_id=video_id, stage=stage.value,
            took=_took(started), error=f"{type(e).__name__}: {message}"[:500],
        )
        await transition_video_status(
            video_id, stage, VideoStatus.FAILED, error_message=message[:_MAX_ERROR_CHARS]
        )
        return

    await _event(video_id, node, "ok", started, {"outcome": outcome.value})
    activity.emit(
        "stage_finished", video_id=video_id, stage=stage.value, took=_took(started),
        outcome="next stage" if outcome is Outcome.NEXT else "waiting for sub-tasks",
    )
    if outcome is Outcome.NEXT:
        await _advance(video_id, stage)


async def _advance(video_id, stage: VideoStatus) -> None:
    try:
        await advance(video_id, stage)
    except QueueUnavailable:
        # advance() already marked the video FAILED; resume retries it.
        logger.exception("Video %s: could not queue the stage after %s", video_id, stage.value)


async def resume(video_id: str) -> bool:
    """Restart a FAILED / WAITING_QUOTA video from current_stage.
    False if the video is missing or not halted."""
    video = await get_video(video_id)
    if video is None or video.status not in VIDEO_HALT_STATUSES or video.current_stage is None:
        return False
    stage = video.current_stage
    if not await transition_video_status(
        video_id, tuple(VIDEO_HALT_STATUSES), stage, error_message=None
    ):
        return False  # someone else resumed it first
    try:
        await asyncio.to_thread(enqueue_stage, video_id, stage)
    except Exception as e:
        await transition_video_status(
            video_id, stage, VideoStatus.FAILED, error_message=f"Queue dispatch failed: {e}"
        )
        raise QueueUnavailable(str(e)) from e
    logger.info("Video %s resumed at %s", video_id, stage.value)
    activity.emit("video_resumed", video_id=video_id, stage=stage.value, was=video.status.value)
    return True


def _stale_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=settings.PIPELINE_STALE_AFTER_S)


def is_stuck(video: VideoOut) -> bool:
    """At a recoverable status and unchanged for PIPELINE_STALE_AFTER_S."""
    updated = video.updated_at
    if updated.tzinfo is None:  # SQLite returns naive datetimes
        updated = updated.replace(tzinfo=timezone.utc)
    return video.status in RECOVERABLE_STATUSES and updated < _stale_cutoff()


async def kick(video_id, status: VideoStatus) -> bool:
    """Re-queue a stuck video at its current status. The compare-and-set to
    the same status bumps updated_at, so concurrent sweepers kick it once and
    the next kick waits another PIPELINE_STALE_AFTER_S. Raises QueueUnavailable."""
    status = VideoStatus(status)
    if status == VideoStatus.WAITING_QUOTA:
        activity.emit(
            "video_stuck", video_id=video_id, stage=status.value,
            action="scheduled quota retry was lost — resuming now",
        )
        return await resume(video_id)
    if not await transition_video_status(video_id, status, status):
        return False
    try:
        await asyncio.to_thread(enqueue_stage, video_id, status)
    except Exception as e:
        await transition_video_status(
            video_id, status, VideoStatus.FAILED, error_message=f"Queue dispatch failed: {e}"
        )
        raise QueueUnavailable(str(e)) from e
    logger.warning("Video %s was stuck at %s — re-queued", video_id, status.value)
    activity.emit(
        "video_stuck", video_id=video_id, stage=status.value,
        idle_over=f"{settings.PIPELINE_STALE_AFTER_S} s", action="re-queued the stage",
    )
    await record_event(
        node_name="sweeper", status="requeued", video_id=video_id, output_summary={"stage": status.value}
    )
    return True


async def sweep_stale() -> int:
    """Re-queue every stuck video. Returns how many were kicked."""
    kicked = 0
    for video_id, status in await list_stale_videos(RECOVERABLE_STATUSES, _stale_cutoff()):
        try:
            if await kick(video_id, status):
                kicked += 1
        except QueueUnavailable:
            logger.exception("Sweeper could not re-queue video %s", video_id)
    if kicked:
        logger.info("Sweeper re-queued %d stuck video(s)", kicked)
    return kicked


def _took(started: float) -> str:
    return f"{time.monotonic() - started:.1f} s"


async def _event(video_id, node: str, status: str, started: float, summary: dict) -> None:
    await record_event(
        node_name=node,
        status=status,
        video_id=video_id,
        latency_ms=int((time.monotonic() - started) * 1000),
        output_summary=summary,
    )
