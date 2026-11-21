from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from app.core.logging import get_logger
from app.repository.scene_repository import delete_scene, get_scene, list_scenes, update_scene_status
from app.repository.video_repository import get_video
from app.schemas.api import SceneListOut, SceneOut
from app.schemas.status import SceneStatus
from app.services.scene_service import ScriptValidationError, generate_and_queue
from app.workers.render_task import scene_media_path

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/",
    response_model=SceneListOut,
    summary="List scenes",
    description="Returns a paginated list of all scenes, newest first.",
)
async def get_scenes(skip: int = 0, limit: int = 20):
    scenes, total = await list_scenes(limit=limit, skip=skip)
    return {"scenes": scenes, "total": total}


@router.get(
    "/{scene_id}",
    response_model=SceneOut,
    summary="Get scene by ID",
    description=(
        "Returns the scene including `status`, `rendered_segment_url` and "
        "`error_message`. Poll this after submitting a prompt to see when "
        "rendering is complete."
    ),
)
async def get_scene_endpoint(scene_id: str):
    scene = await get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@router.post(
    "/{scene_id}/regenerate",
    response_model=SceneOut,
    status_code=202,
    summary="Regenerate scene",
    description=(
        "Re-runs LLM → validate → render for an existing scene using its video's "
        "prompt. Resets the scene to `pending` and clears its script, video and "
        "error. Returns 202 with the scene."
    ),
)
async def regenerate_scene(scene_id: str):
    scene = await get_scene(scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    video = await get_video(scene.video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    logger.info("Regenerating scene %s", scene_id)

    await update_scene_status(
        scene_id,
        SceneStatus.PENDING,
        generated_script=None,
        rendered_segment_url=None,
        error_message=None,
    )

    try:
        await generate_and_queue(str(video.id), scene_id, video.user_prompt)
    except ScriptValidationError as e:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Script validation failed: {e.message}", "code": "VALIDATION_ERROR"},
        )
    except Exception:
        logger.exception("Unexpected error regenerating scene %s", scene_id)
        raise HTTPException(status_code=500, detail="Script generation failed")

    return JSONResponse(status_code=202, content=(await get_scene(scene_id)).model_dump(mode="json"))


@router.delete(
    "/{scene_id}",
    status_code=204,
    summary="Delete scene",
    description=(
        "Deletes the scene and its rendered file, if any. The parent video is kept "
        "(`DELETE /videos/{id}` arrives in step 5). Returns 204 No Content."
    ),
)
async def delete_scene_endpoint(scene_id: str):
    scene = await get_scene(scene_id)
    if not scene or not await delete_scene(scene_id):
        raise HTTPException(status_code=404, detail="Scene not found")
    path, _ = scene_media_path(str(scene.video_id), scene_id)
    path.unlink(missing_ok=True)
    logger.info("Scene %s deleted", scene_id)
    return Response(status_code=204)
