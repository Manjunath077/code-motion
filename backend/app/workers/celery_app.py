from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "code-motion",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.render_task", "app.workers.pipeline_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Acknowledge a task only after it finished, and re-queue it if the
    # worker process dies mid-task — a crashed stage is retried, not lost.
    # Stage handlers are written to be safe to repeat.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # One task at a time per process: stages are long, don't hoard them.
    worker_prefetch_multiplier=1,
    # Celery beat (the `beat` compose service) schedules the stuck-video sweeper.
    beat_schedule={
        "sweep-stale-videos": {
            "task": "sweep_stale_videos",
            "schedule": float(settings.PIPELINE_SWEEP_INTERVAL_S),
        },
    },
)
