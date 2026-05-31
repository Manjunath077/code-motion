import asyncio
from app.services.llm_service import generate_manim_script, fix_manim_script
from app.repository.scene_repository import (
    update_scene_status,
    update_scene_script,
)
from app.schemas.scene_schema import SceneStatus
from app.utils.script_validator import validate_manim_script
from app.workers.render_task import render_scene
from app.core.logging import get_logger

logger = get_logger(__name__)


_MAX_REPAIR_ATTEMPTS = 2


class ScriptValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def generate_and_queue(scene_id: str, prompt: str) -> None:
    """
    Full pipeline: LLM generate → AST validate (with repair retries) → persist → dispatch to render queue.
    Updates scene status at every step.
    Raises ScriptValidationError if validation fails after all repair attempts.
    Re-raises any LLM or queue exception (scene already marked failed).
    """
    # — LLM —
    try:
        script = await generate_manim_script(prompt)
    except Exception as e:
        await update_scene_status(scene_id, SceneStatus.FAILED, error_message=str(e))
        logger.exception("LLM generation failed for scene %s", scene_id)
        raise

    # — Validation with repair loop —
    for attempt in range(_MAX_REPAIR_ATTEMPTS + 1):
        await update_scene_status(scene_id, SceneStatus.VALIDATING)
        result = validate_manim_script(script)
        if result.is_valid:
            break

        if attempt < _MAX_REPAIR_ATTEMPTS:
            logger.warning(
                "Validation failed (attempt %d/%d) for scene %s: %s — retrying repair",
                attempt + 1, _MAX_REPAIR_ATTEMPTS + 1, scene_id, result.error,
            )
            try:
                script = await fix_manim_script(script, result.error)
            except Exception as e:
                await update_scene_status(scene_id, SceneStatus.FAILED, error_message=str(e))
                logger.exception("Script repair LLM call failed for scene %s", scene_id)
                raise
        else:
            await update_scene_status(scene_id, SceneStatus.FAILED, error_message=result.error)
            logger.warning(
                "Validation failed after %d repair attempts for scene %s: %s",
                _MAX_REPAIR_ATTEMPTS, scene_id, result.error,
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
