"""Daily free-request budget check (NEW_PLAN.md Section 4).

OpenRouter reports the account's remaining free-model requests for today at
`GET {OPENROUTER_BASE_URL}/key` under `data.free_model_daily_requests.remaining`.
The value is cached in Redis for 60 s so it is not fetched before every call.
Below LLM_DAILY_RESERVE, calls are refused with QuotaExhausted.
"""
from typing import Optional

import httpx

from app.core import redis_client
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CACHE_KEY = "llm:quota:remaining"
_CACHE_TTL_S = 60


class QuotaExhausted(Exception):
    """Today's free-model request budget is used up (or below the reserve)."""


async def _fetch_remaining() -> Optional[int]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{settings.OPENROUTER_BASE_URL}/key",
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
        )
        resp.raise_for_status()
    data = resp.json().get("data") or {}
    remaining = (data.get("free_model_daily_requests") or {}).get("remaining")
    return None if remaining is None else int(remaining)


async def remaining_requests(force_refresh: bool = False) -> Optional[int]:
    """Remaining free requests today, or None if OpenRouter did not say."""
    async with redis_client.get_redis() as r:
        if not force_refresh:
            cached = await r.get(_CACHE_KEY)
            if cached is not None:
                return int(cached)

        try:
            remaining = await _fetch_remaining()
        except httpx.HTTPError as e:
            # Unknown is not the same as exhausted — let the call go ahead;
            # a real daily-cap 429 is still caught by force_refresh later.
            logger.warning("Could not read OpenRouter quota: %s", e)
            return None

        if remaining is None:
            logger.warning("OpenRouter /key response has no free_model_daily_requests.remaining")
            return None

        await r.set(_CACHE_KEY, remaining, ex=_CACHE_TTL_S)
        return remaining


async def ensure_quota(force_refresh: bool = False) -> None:
    remaining = await remaining_requests(force_refresh=force_refresh)
    if remaining is not None and remaining < settings.LLM_DAILY_RESERVE:
        raise QuotaExhausted(
            f"Only {remaining} free OpenRouter requests left today "
            f"(reserve is {settings.LLM_DAILY_RESERVE}) — try again after the daily reset (00:00 UTC)"
        )
