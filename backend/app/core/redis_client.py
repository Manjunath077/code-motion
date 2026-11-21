"""Shared Redis connection factory for the LLM rate limiter and quota cache.

A fresh client is created per use (`async with get_redis() as r:`) rather than
cached at module level: async Redis connections are bound to the event loop
that opened them, and Celery tasks may run each call in a new loop.
Tests replace `get_redis` with a fakeredis factory.
"""
import redis.asyncio as redis

from app.core.config import settings


def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)
