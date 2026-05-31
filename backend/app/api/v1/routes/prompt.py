from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from app.schemas.prompt_schema import PromptRequest
from app.schemas.scene_schema import SceneStatus, QueuedResponse
from app.repository.scene_repository import create_scene
from app.services.scene_service import generate_and_queue, ScriptValidationError
from app.core.limiter import limiter
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/",
    response_model=QueuedResponse,
    status_code=202,
    summary="Generate Manim Script",
    description=(
        "Accepts a natural-language prompt, calls the LLM to generate a Manim "
        "Python script, validates it, persists a Scene document, and enqueues a "
        "Celery render job. Returns 202 immediately with the scene ID so the "
        "frontend can poll `GET /scenes/{scene_id}` for completion."
    ),
)
@limiter.limit("10/minute")
async def generate_script(request: Request, body: PromptRequest):
    logger.info("Prompt received: %s", body.prompt[:80])

    scene = await create_scene(body.prompt)

    try:
        await generate_and_queue(scene.id, body.prompt)
    except ScriptValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Script validation failed: {e.message}", "code": "VALIDATION_ERROR"},
        )
    except Exception:
        logger.exception("Unexpected error processing prompt for scene %s", scene.id)
        raise HTTPException(status_code=500, detail="Script generation failed")

    return JSONResponse(
        status_code=202,
        content={"scene_id": scene.id, "status": SceneStatus.QUEUED},
    )
