from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "code-motion",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.render_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
)
