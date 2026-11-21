"""Interim single-shot flow: prompt → one scene → codegen → AST check → render.
Replaced by the stage runner in NEW_PLAN.md step 5.

Video and scene statuses are set separately:
    video: CREATED → CODEGEN → FINAL_RENDER → COMPLETED / FAILED
    scene: PENDING → CODEGEN → STATIC_CHECK → APPROVED → RENDERED / FAILED
"""
import asyncio

from app.core.logging import get_logger
from app.repository.scene_repository import update_scene_status
from app.repository.video_repository import update_video_status
from app.schemas.status import SceneStatus, VideoStatus
from app.services.llm_service import fix_manim_script, generate_manim_script
from app.utils.script_validator import ValidationResult, validate_manim_script
from app.workers.render_task import render_scene

logger = get_logger(__name__)

_MAX_REPAIR_ATTEMPTS = 2


class ScriptValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def _generate_valid_script(scene_id: str, prompt: str) -> tuple[str, ValidationResult]:
    """Generate → AST-validate → repair (at most _MAX_REPAIR_ATTEMPTS times).
    Returns the last script and its validation result, valid or not."""
    await update_scene_status(scene_id, SceneStatus.CODEGEN)
    script = await generate_manim_script(prompt, scene_id=scene_id)

    await update_scene_status(scene_id, SceneStatus.STATIC_CHECK)
    result = validate_manim_script(script)

    repairs = 0
    while not result.is_valid and repairs < _MAX_REPAIR_ATTEMPTS:
        repairs += 1
        script = await fix_manim_script(script, result.error, scene_id=scene_id)
        result = validate_manim_script(script)

    return script, result


async def _fail(video_id: str, scene_id: str, message: str) -> None:
    await update_scene_status(scene_id, SceneStatus.FAILED, error_message=message)
    await update_video_status(video_id, VideoStatus.FAILED, error_message=message)


async def generate_and_queue(video_id: str, scene_id: str, prompt: str) -> None:
    """
    Generate → AST validate (with repair retries) → persist → dispatch to render queue.
    Raises ScriptValidationError if validation fails after all repair attempts.
    Re-raises any LLM or queue exception (scene and video already marked failed).
    """
    await update_video_status(video_id, VideoStatus.CODEGEN, error_message=None)
    try:
        script, result = await _generate_valid_script(scene_id, prompt)
    except Exception as e:
        await _fail(video_id, scene_id, str(e))
        logger.exception("Script generation failed for scene %s", scene_id)
        raise

    if not result.is_valid:
        await _fail(video_id, scene_id, result.error)
        logger.warning(
            "Validation failed after repair attempts for scene %s: %s",
            scene_id, result.error,
        )
        raise ScriptValidationError(result.error)

    await update_scene_status(scene_id, SceneStatus.APPROVED, generated_script=script)
    await update_video_status(video_id, VideoStatus.FINAL_RENDER)

    # — Dispatch to Celery/Redis queue —
    try:
        await asyncio.to_thread(render_scene.delay, scene_id)
        logger.info("Scene %s dispatched to render queue", scene_id)
    except Exception as e:
        # Redis is unreachable or Celery broker is down.
        # Mark FAILED so the scene is not stuck waiting for a render forever.
        await _fail(video_id, scene_id, f"Queue dispatch failed: {e}")
        logger.exception(
            "Failed to dispatch render task for scene %s — is Redis running?", scene_id
        )
        raise RuntimeError(f"Queue dispatch failed: {e}") from e
