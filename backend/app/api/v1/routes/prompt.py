from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.limiter import limiter
from app.core.logging import get_logger
from app.repository.scene_repository import create_scene
from app.repository.video_repository import create_video, get_video
from app.schemas.api import VideoCreate, VideoOut
from app.services.scene_service import ScriptValidationError, generate_and_queue

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/",
    response_model=VideoOut,
    status_code=202,
    summary="Generate a one-scene video",
    description=(
        "Interim single-shot flow (replaced by `POST /videos` in step 5): creates a "
        "video with one scene, calls the LLM to write a Manim script, validates it "
        "and enqueues a Celery render. Returns 202 with the video and its scene; "
        "poll `GET /scenes/{scene_id}` for completion."
    ),
)
@limiter.limit("10/minute")
async def generate_script(request: Request, body: VideoCreate):
    logger.info("Prompt received: %s", body.prompt[:80])

    video = await create_video(body.prompt, review_mode=body.review_mode)
    scene = await create_scene(video.id, order=0)

    try:
        await generate_and_queue(str(video.id), str(scene.id), body.prompt)
    except ScriptValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Script validation failed: {e.message}", "code": "VALIDATION_ERROR"},
        )
    except Exception:
        logger.exception("Unexpected error processing prompt for video %s", video.id)
        raise HTTPException(status_code=500, detail="Script generation failed")

    return JSONResponse(status_code=202, content=(await get_video(video.id)).model_dump(mode="json"))
