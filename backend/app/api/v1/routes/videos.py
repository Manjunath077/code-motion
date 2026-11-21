"""Videos API. Requests never call the LLM: they create or change the job and
return; Celery workers run the pipeline (app/pipeline)."""
import shutil
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.core import activity
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.core.media import video_media_dir
from app.pipeline import runner
from app.pipeline.transitions import QueueUnavailable, start
from app.repository.video_repository import create_video, delete_video, get_video, list_videos
from app.schemas.api import VideoCreate, VideoListOut, VideoOut
from app.schemas.status import VIDEO_HALT_STATUSES

router = APIRouter()
logger = get_logger(__name__)

_QUEUE_DOWN = "Job queue unavailable — the video is marked failed; resume it once Redis is back"


async def _video_or_404(video_id: UUID) -> VideoOut:
    video = await get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def _accepted(video: VideoOut) -> JSONResponse:
    return JSONResponse(status_code=202, content=video.model_dump(mode="json"))


@router.post(
    "",
    response_model=VideoOut,
    status_code=202,
    summary="Create a video",
    description=(
        "Creates the job and queues its first stage. Returns 202 immediately — "
        "no LLM call happens in this request. Poll `GET /videos/{id}` for progress."
    ),
)
@limiter.limit("10/minute")
async def create_video_endpoint(request: Request, body: VideoCreate):
    video = await create_video(body.prompt, review_mode=body.review_mode)
    logger.info("Video %s created: %s", video.id, body.prompt[:80])
    activity.emit("video_created", video_id=video.id, prompt=body.prompt[:200], review_mode=body.review_mode)
    try:
        await start(video.id)
    except QueueUnavailable:
        raise HTTPException(status_code=503, detail=_QUEUE_DOWN)
    return _accepted(await get_video(video.id))


@router.get(
    "",
    response_model=VideoListOut,
    summary="List videos",
    description="Paginated, newest first, each with its scenes.",
)
async def list_videos_endpoint(skip: int = 0, limit: int = 20):
    videos, total = await list_videos(limit=limit, skip=skip)
    return {"videos": videos, "total": total}


@router.get(
    "/{video_id}",
    response_model=VideoOut,
    summary="Get a video",
    description="Status, current stage, artifacts and scenes.",
)
async def get_video_endpoint(video_id: UUID):
    return await _video_or_404(video_id)


@router.post(
    "/{video_id}/resume",
    response_model=VideoOut,
    status_code=202,
    summary="Resume a halted or stuck video",
    description=(
        "Restarts a `failed` or `waiting_quota` video from its `current_stage`, or "
        "re-queues a video stuck at a stage (unchanged for `PIPELINE_STALE_AFTER_S`). "
        "409 if the video is progressing normally, completed, or awaiting approval."
    ),
)
async def resume_video_endpoint(video_id: UUID):
    video = await _video_or_404(video_id)
    try:
        if video.status in VIDEO_HALT_STATUSES:
            done = await runner.resume(video_id)
        elif runner.is_stuck(video):
            done = await runner.kick(video_id, video.status)
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Video is {video.status.value} and not stuck — nothing to resume",
            )
    except QueueUnavailable:
        raise HTTPException(status_code=503, detail=_QUEUE_DOWN)
    if not done:
        raise HTTPException(status_code=409, detail="Video was resumed by someone else")
    return _accepted(await get_video(video_id))


@router.delete(
    "/{video_id}",
    status_code=204,
    summary="Delete a video",
    description="Deletes the video, its scenes and attempts, and its media folder.",
)
async def delete_video_endpoint(video_id: UUID):
    if not await delete_video(video_id):
        raise HTTPException(status_code=404, detail="Video not found")
    shutil.rmtree(video_media_dir(video_id), ignore_errors=True)
    logger.info("Video %s deleted", video_id)
    return Response(status_code=204)
