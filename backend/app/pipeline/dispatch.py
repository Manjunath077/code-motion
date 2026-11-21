"""Queue Celery tasks by name, so pipeline code never imports the task
modules (which import the pipeline back). Every function is sync and may
block on Redis: call it through asyncio.to_thread from async code."""
from app.schemas.status import VideoStatus
from app.workers.celery_app import celery_app


def enqueue_stage(video_id, stage: VideoStatus) -> None:
    celery_app.send_task("run_stage", args=[str(video_id), VideoStatus(stage).value])


def enqueue_render(scene_id) -> None:
    celery_app.send_task("render_scene", args=[str(scene_id)])


def schedule_resume(video_id, countdown_s: int) -> None:
    celery_app.send_task("resume_video", args=[str(video_id)], countdown=countdown_s)
