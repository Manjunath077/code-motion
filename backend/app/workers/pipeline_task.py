"""Celery entry points for the pipeline state machine."""
import asyncio
from typing import Awaitable, Callable

from app.core.logging import get_logger
from app.db.session import engine
from app.pipeline import runner
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


def _run_async(make: Callable[[], Awaitable]) -> None:
    """Run a coroutine in a fresh event loop. The async engine's pooled
    connections belong to the loop that opened them, so they are disposed
    before this loop closes; the next task opens new ones."""
    async def main():
        try:
            await make()
        finally:
            await engine.dispose()

    asyncio.run(main())


@celery_app.task(name="run_stage")
def run_stage(video_id: str, stage: str) -> None:
    _run_async(lambda: runner.run_stage(video_id, stage))


@celery_app.task(name="sweep_stale_videos")
def sweep_stale_videos() -> None:
    """Run by Celery beat every PIPELINE_SWEEP_INTERVAL_S: re-queue videos
    whose task was lost (see runner.kick)."""
    _run_async(runner.sweep_stale)


@celery_app.task(name="resume_video")
def resume_video(video_id: str) -> None:
    """Scheduled retry for a video in WAITING_QUOTA (and the target of the
    resume endpoint's logic). A no-op if the video is no longer halted."""
    _run_async(lambda: runner.resume(video_id))
