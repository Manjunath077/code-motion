"""LLM rate limiter shared by the API and every Celery worker (NEW_PLAN.md Section 4).

OpenRouter's :free models allow 20 requests/minute account-wide, so the limit
has to be enforced across processes — a per-process limiter (e.g. aiolimiter)
lets N workers send N times the limit. This is a sliding 60-second window kept
in a Redis sorted set; the check-and-add runs as one Lua script so two
processes can never both take the last slot.
"""
import asyncio
import time
import uuid

from app.core import activity, redis_client
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_KEY = "llm:rate_limit"
_WINDOW_MS = 60_000

# Returns 0 if a slot was taken, otherwise the milliseconds to wait until the
# oldest request leaves the window.
_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, now, ARGV[4])
  redis.call('PEXPIRE', key, window)
  return 0
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
return tonumber(oldest[2]) + window - now
"""


async def acquire() -> None:
    """Block until a request slot is free, then take it."""
    async with redis_client.get_redis() as r:
        while True:
            now_ms = int(time.time() * 1000)
            wait_ms = int(
                await r.eval(_ACQUIRE_SCRIPT, 1, _KEY, now_ms, _WINDOW_MS, settings.LLM_RPM, uuid.uuid4().hex)
            )
            if wait_ms <= 0:
                return
            logger.info("LLM rate limit reached (%d/min) — waiting %d ms", settings.LLM_RPM, wait_ms)
            activity.emit("rate_limit_wait", limit=f"{settings.LLM_RPM}/min", wait=f"{wait_ms / 1000:.1f} s")
            await asyncio.sleep(wait_ms / 1000)
