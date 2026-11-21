from unittest.mock import AsyncMock

import httpx
import pytest

from app.core import quota
from app.core.config import settings
from app.core.quota import QuotaExhausted


@pytest.fixture
def fetch(monkeypatch):
    mock = AsyncMock(return_value=900)
    monkeypatch.setattr(quota, "_fetch_remaining", mock)
    return mock


async def test_remaining_is_cached(fake_redis, fetch):
    assert await quota.remaining_requests() == 900
    assert await quota.remaining_requests() == 900
    assert fetch.await_count == 1


async def test_force_refresh_bypasses_cache(fake_redis, fetch):
    await quota.remaining_requests()
    fetch.return_value = 10
    assert await quota.remaining_requests(force_refresh=True) == 10
    assert fetch.await_count == 2


async def test_ensure_quota_passes_above_reserve(fake_redis, fetch):
    fetch.return_value = settings.LLM_DAILY_RESERVE
    await quota.ensure_quota()


async def test_ensure_quota_raises_below_reserve(fake_redis, fetch):
    fetch.return_value = settings.LLM_DAILY_RESERVE - 1
    with pytest.raises(QuotaExhausted):
        await quota.ensure_quota()


async def test_unknown_remaining_does_not_block(fake_redis, fetch):
    fetch.return_value = None
    await quota.ensure_quota()


async def test_http_error_does_not_block(fake_redis, fetch):
    fetch.side_effect = httpx.ConnectError("down")
    assert await quota.remaining_requests() is None
    await quota.ensure_quota()


async def test_fetch_reads_key_endpoint(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": {"free_model_daily_requests": {"limit": 1000, "remaining": 742}}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        quota.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )

    assert await quota._fetch_remaining() == 742
    assert seen["url"] == f"{settings.OPENROUTER_BASE_URL}/key"
    assert seen["auth"] == f"Bearer {settings.OPENROUTER_API_KEY}"
