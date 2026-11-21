"""Stage order and stage handlers.

A handler is `async def handler(video: VideoOut) -> Outcome`. It saves its
own output (artifacts, scenes) and returns:
    NEXT — done; the runner advances the video to the next stage.
    WAIT — work continues elsewhere (e.g. scene renders); whoever finishes
           it advances the video (see transitions.scene_render_finished_sync).
It raises on failure; the runner marks the video FAILED (or WAITING_QUOTA
on QuotaExhausted) and keeps current_stage for resume.

Stages without a handler are skipped. Until their steps land (NEW_PLAN.md
section 6), the pipeline runs: CREATED → CODEGEN → FINAL_RENDER → ASSEMBLE →
COMPLETED, with interim single-scene handlers below.

Handlers may run more than once for the same video (a task redelivered after
a worker crash, or a resume), so they must be safe to repeat.
"""
import asyncio
from enum import Enum
from typing import Awaitable, Callable

from app.core.logging import get_logger
from app.pipeline.dispatch import enqueue_render
from app.repository.scene_repository import create_scene, update_scene_status
from app.repository.video_repository import update_video
from app.schemas.api import VideoOut
from app.schemas.status import SceneStatus, VideoStatus
from app.services.llm_service import fix_manim_script, generate_manim_script
from app.utils.script_validator import validate_manim_script

logger = get_logger(__name__)


class Outcome(Enum):
    NEXT = "next"
    WAIT = "wait"


class StageError(Exception):
    """A stage failed for a reason worth showing the user as error_message."""


# Full order, including stages that have no handler yet.
PIPELINE: tuple[VideoStatus, ...] = (
    VideoStatus.CREATED,
    VideoStatus.SPEC,
    VideoStatus.TRACE,
    VideoStatus.OUTLINE,
    VideoStatus.STORYBOARD,
    VideoStatus.AWAITING_APPROVAL,
    VideoStatus.CODEGEN,
    VideoStatus.QA,
    VideoStatus.TTS,
    VideoStatus.FINAL_RENDER,
    VideoStatus.ASSEMBLE,
    VideoStatus.COMPLETED,
)

_MAX_REPAIR_ATTEMPTS = 2


# ── [5] CODEGEN — interim: one scene straight from the prompt (step 9 replaces) ──

async def codegen(video: VideoOut) -> Outcome:
    """Generate → AST-validate → repair (at most _MAX_REPAIR_ATTEMPTS times)."""
    scene = video.scenes[0] if video.scenes else await create_scene(video.id, order=0)
    scene_id = str(scene.id)
    try:
        await update_scene_status(scene_id, SceneStatus.CODEGEN, error_message=None)
        script = await generate_manim_script(video.user_prompt, scene_id=scene_id)

        await update_scene_status(scene_id, SceneStatus.STATIC_CHECK)
        result = validate_manim_script(script)
        repairs = 0
        while not result.is_valid and repairs < _MAX_REPAIR_ATTEMPTS:
            repairs += 1
            script = await fix_manim_script(script, result.error, scene_id=scene_id)
            result = validate_manim_script(script)
    except Exception as e:
        await update_scene_status(scene_id, SceneStatus.FAILED, error_message=str(e))
        raise

    if not result.is_valid:
        message = f"Script validation failed: {result.error}"
        await update_scene_status(scene_id, SceneStatus.FAILED, error_message=message)
        raise StageError(message)

    await update_scene_status(scene_id, SceneStatus.APPROVED, generated_script=script)
    return Outcome.NEXT


# ── [7] FINAL_RENDER — one Celery render task per scene, fan-in on the last ──

async def final_render(video: VideoOut) -> Outcome:
    if not video.scenes:
        raise StageError("No scenes to render")
    pending = [s for s in video.scenes if s.status != SceneStatus.RENDERED]
    if not pending:
        return Outcome.NEXT  # resumed after every scene had already rendered
    for scene in pending:
        if not scene.generated_script:
            raise StageError(f"Scene {scene.order} has no script")
    for scene in pending:
        await update_scene_status(scene.id, SceneStatus.APPROVED, error_message=None)
        await asyncio.to_thread(enqueue_render, scene.id)
    logger.info("Video %s: %d scene render(s) queued", video.id, len(pending))
    return Outcome.WAIT


# ── [8] ASSEMBLE — interim: a one-scene video is its scene (step 13 replaces) ──

async def assemble(video: VideoOut) -> Outcome:
    if len(video.scenes) != 1:
        raise StageError("Assembling more than one scene arrives in step 13")
    scene = video.scenes[0]
    if scene.status != SceneStatus.RENDERED or not scene.rendered_segment_url:
        raise StageError("Scene is not rendered")
    await update_video(video.id, final_video_url=scene.rendered_segment_url)
    return Outcome.NEXT


Handler = Callable[[VideoOut], Awaitable[Outcome]]

HANDLERS: dict[VideoStatus, Handler] = {
    VideoStatus.CODEGEN: codegen,
    VideoStatus.FINAL_RENDER: final_render,
    VideoStatus.ASSEMBLE: assemble,
}


def next_stage(stage: VideoStatus) -> VideoStatus:
    """The next stage that has a handler, or COMPLETED."""
    index = PIPELINE.index(VideoStatus(stage))  # ValueError for FAILED / WAITING_QUOTA
    for candidate in PIPELINE[index + 1:]:
        if candidate in HANDLERS or candidate == VideoStatus.COMPLETED:
            return candidate
    raise ValueError(f"{stage} has no next stage")
