import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from app.repository.scene_repository import (
    get_scene_by_id,
    list_scenes,
    delete_scene,
    update_scene_status,
)
from app.schemas.scene_schema import SceneDocument, SceneStatus, ScenesListResponse, QueuedResponse
from app.services.scene_service import generate_and_queue, ScriptValidationError
from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/",
    response_model=ScenesListResponse,
    summary="List scenes",
    description="Returns a paginated list of all scenes ordered by creation date (newest first).",
)
async def get_scenes(skip: int = 0, limit: int = 20):
    scenes, total = await list_scenes(limit=limit, skip=skip)
    return {"scenes": scenes, "total": total}


@router.get(
    "/{scene_id}",
    response_model=SceneDocument,
    summary="Get scene by ID",
    description=(
        "Returns the full scene document including `status`, `video_url`, and "
        "`error_message`. Poll this endpoint after submitting a prompt to check "
        "when rendering is complete."
    ),
)
async def get_scene(scene_id: str):
    scene = await get_scene_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@router.post(
    "/{scene_id}/regenerate",
    response_model=QueuedResponse,
    status_code=202,
    summary="Regenerate scene",
    description=(
        "Re-runs the full LLM → validate → render pipeline for an existing scene "
        "using its original prompt. Resets status to `pending` and clears any "
        "previous script, video, or error. Returns 202 with the same scene ID."
    ),
)
async def regenerate_scene(scene_id: str):
    scene = await get_scene_by_id(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    logger.info("Regenerating scene %s", scene_id)

    await update_scene_status(
        scene_id,
        SceneStatus.PENDING,
        generated_script=None,
        video_url=None,
        error_message=None,
    )

    try:
        await generate_and_queue(scene_id, scene.prompt)
    except ScriptValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Script validation failed: {e.message}", "code": "VALIDATION_ERROR"},
        )
    except Exception:
        logger.exception("Unexpected error regenerating scene %s", scene_id)
        raise HTTPException(status_code=500, detail="Script generation failed")

    return JSONResponse(
        status_code=202,
        content={"scene_id": scene_id, "status": SceneStatus.QUEUED},
    )


@router.delete(
    "/{scene_id}",
    status_code=204,
    summary="Delete scene",
    description=(
        "Deletes the scene document from MongoDB and removes the rendered video "
        "from disk if it exists. Returns 204 No Content on success."
    ),
)
async def delete_scene_endpoint(scene_id: str):
    deleted = await delete_scene(scene_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scene not found")
    video_dir = Path(settings.MEDIA_DIR) / scene_id
    if video_dir.exists():
        shutil.rmtree(str(video_dir), ignore_errors=True)
    logger.info("Scene %s deleted", scene_id)
    return Response(status_code=204)
