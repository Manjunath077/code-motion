import asyncio

from app.core.logging import get_logger
from app.repository.scene_repository import update_scene_script, update_scene_status
from app.schemas.scene_schema import SceneStatus
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
    await update_scene_status(scene_id, SceneStatus.VALIDATING)

    script = await generate_manim_script(prompt, scene_id=scene_id)
    result = validate_manim_script(script)

    repairs = 0
    while not result.is_valid and repairs < _MAX_REPAIR_ATTEMPTS:
        repairs += 1
        script = await fix_manim_script(script, result.error, scene_id=scene_id)
        result = validate_manim_script(script)

    return script, result


async def generate_and_queue(scene_id: str, prompt: str) -> None:
    """
    Full pipeline: generate → AST validate (with repair retries) → persist → dispatch to render queue.
    Updates scene status at every step.
    Raises ScriptValidationError if validation fails after all repair attempts.
    Re-raises any LLM or queue exception (scene already marked failed).
    """
    try:
        script, result = await _generate_valid_script(scene_id, prompt)
    except Exception as e:
        await update_scene_status(scene_id, SceneStatus.FAILED, error_message=str(e))
        logger.exception("Script generation failed for scene %s", scene_id)
        raise

    if not result.is_valid:
        await update_scene_status(scene_id, SceneStatus.FAILED, error_message=result.error)
        logger.warning(
            "Validation failed after repair attempts for scene %s: %s",
            scene_id, result.error,
        )
        raise ScriptValidationError(result.error)

    # — Persist script —
    await update_scene_script(scene_id, script)

    # — Dispatch to Celery/Redis queue —
    await update_scene_status(scene_id, SceneStatus.QUEUED)
    try:
        await asyncio.to_thread(render_scene.delay, scene_id)
        logger.info("Scene %s dispatched to render queue", scene_id)
    except Exception as e:
        # Redis is unreachable or Celery broker is down.
        # Roll the status back to FAILED so the scene is not stuck as QUEUED forever.
        await update_scene_status(
            scene_id,
            SceneStatus.FAILED,
            error_message=f"Queue dispatch failed: {e}",
        )
        logger.exception(
            "Failed to dispatch render task for scene %s — is Redis running?", scene_id
        )
        raise RuntimeError(f"Queue dispatch failed: {e}") from e
