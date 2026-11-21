"""Pipeline activity feed: one place to see what every process is doing.

The API, the Celery workers and the LLM router run in different processes
(the workers in containers), so their logs land in different terminals. Each
of them publishes short events here; the API prints them as bordered blocks
in the uvicorn log (app/core/activity_console.py).

Transport: a Redis Stream (STREAM), capped at about _MAXLEN entries. Events
are fire-and-forget: publishing never raises and never blocks for more than
_TIMEOUT_S, so a Redis hiccup can't fail a stage. The step 13 progress feed
(SSE) can read the same stream.

Event kinds (titles and colours: KINDS in app/core/activity_console.py):
  video_created, stage_queued, stage_started, stage_finished, stage_failed,
  waiting_quota, llm_call, llm_answer, llm_error, rate_limit_wait,
  render_started, render_finished, render_failed,
  video_stuck, video_resumed, video_completed, video_failed
"""
import json
import time
from typing import Any, Optional

import redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

STREAM = "pipeline:activity"
_MAXLEN = 5000
_TIMEOUT_S = 1.0

_client: Optional[redis.Redis] = None
_warned = False


def _redis() -> redis.Redis:
    # One sync client per process. redis-py resets its pool after a fork, so
    # this is safe in Celery's prefork children.
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=_TIMEOUT_S,
            socket_timeout=_TIMEOUT_S,
        )
    return _client


def _source() -> str:
    """'worker' inside a Celery task, else 'api'."""
    try:
        from celery import current_task

        if current_task and current_task.request.id:
            return "worker"
    except Exception:
        pass
    return "api"


def emit(kind: str, *, video_id: Any = None, scene_id: Any = None, **details: Any) -> None:
    """Publish one activity event. Never raises."""
    global _warned
    if not settings.ACTIVITY_FEED_ENABLED:
        return
    fields = {"kind": kind, "ts": f"{time.time():.3f}", "source": _source()}
    if video_id is not None:
        fields["video_id"] = str(video_id)
    if scene_id is not None:
        fields["scene_id"] = str(scene_id)
    fields["details"] = json.dumps(details, default=str)
    try:
        _redis().xadd(STREAM, fields, maxlen=_MAXLEN, approximate=True)
        _warned = False
    except Exception as e:
        if not _warned:  # once per outage, not once per event
            logger.warning("Activity feed unavailable (%s) — events are not published", e)
            _warned = True
