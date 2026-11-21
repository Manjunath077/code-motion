from types import SimpleNamespace

import pytest

from app.core import rate_limiter
from app.core.config import settings


@pytest.fixture
def fake_clock(monkeypatch):
    """Freeze wall-clock time; sleeping advances it instead of waiting."""
    clock = {"ms": 1_000_000}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["ms"] += int(seconds * 1000)

    monkeypatch.setattr(rate_limiter, "time", SimpleNamespace(time=lambda: clock["ms"] / 1000))
    monkeypatch.setattr(rate_limiter, "asyncio", SimpleNamespace(sleep=fake_sleep))
    return sleeps


async def test_allows_up_to_limit_without_waiting(fake_redis, fake_clock, monkeypatch):
    monkeypatch.setattr(settings, "LLM_RPM", 3)

    for _ in range(3):
        await rate_limiter.acquire()

    assert fake_clock == []


async def test_waits_for_oldest_slot_when_window_full(fake_redis, fake_clock, monkeypatch):
    monkeypatch.setattr(settings, "LLM_RPM", 3)

    for _ in range(4):
        await rate_limiter.acquire()

    # All three slots were taken at the same instant, so the fourth call
    # waits the full 60 s window and then gets in.
    assert fake_clock == [60.0]


async def test_limit_is_shared_across_clients(fake_redis, fake_clock, monkeypatch):
    """Every acquire() opens its own Redis client (as separate worker processes
    would); the window still counts all of them together."""
    monkeypatch.setattr(settings, "LLM_RPM", 2)

    await rate_limiter.acquire()
    await rate_limiter.acquire()
    async with fake_redis() as r:
        assert await r.zcard(rate_limiter._KEY) == 2

    await rate_limiter.acquire()
    assert len(fake_clock) == 1
