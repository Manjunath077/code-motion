import asyncio
import json
from unittest.mock import MagicMock

import fakeredis
import pytest

from app.core import activity, activity_console
from app.core.config import settings

pytestmark = pytest.mark.unit


@pytest.fixture
def feed(monkeypatch):
    """Activity feed on, backed by one fakeredis server (sync publisher and
    async console share it, like processes sharing one real Redis)."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(settings, "ACTIVITY_FEED_ENABLED", True)
    monkeypatch.setattr(activity, "_client", fakeredis.FakeRedis(server=server, decode_responses=True))
    monkeypatch.setattr(
        "app.core.redis_client.get_redis",
        lambda: fakeredis.FakeAsyncRedis(server=server, decode_responses=True),
    )
    return activity._client


def test_emit_publishes_event(feed):
    activity.emit("llm_answer", video_id="v1", stage="codegen", took="1.2 s")

    [(_, fields)] = feed.xrange(activity.STREAM)
    assert fields["kind"] == "llm_answer"
    assert fields["video_id"] == "v1"
    assert fields["source"] == "api"
    assert "scene_id" not in fields
    assert json.loads(fields["details"]) == {"stage": "codegen", "took": "1.2 s"}


def test_emit_disabled_publishes_nothing(feed, monkeypatch):
    monkeypatch.setattr(settings, "ACTIVITY_FEED_ENABLED", False)
    activity.emit("video_created", video_id="v1")
    assert feed.xlen(activity.STREAM) == 0


def test_emit_never_raises_when_redis_is_down(monkeypatch):
    monkeypatch.setattr(settings, "ACTIVITY_FEED_ENABLED", True)
    broken = MagicMock()
    broken.xadd.side_effect = ConnectionError("redis down")
    monkeypatch.setattr(activity, "_client", broken)

    activity.emit("stage_started", video_id="v1")  # must not raise
    activity.emit("stage_started", video_id="v1")
    assert broken.xadd.call_count == 2


def test_render_is_a_closed_box_of_equal_width():
    block = activity_console.render({
        "kind": "render_failed", "ts": "1763727430.5", "source": "worker",
        "video_id": "4ae8067c-6ebf-4131-b816-1fb414480b9a",
        "details": json.dumps({"took": "3.1 s", "error": "line one\nline two " + "x" * 200, "skip": None}),
    })
    lines = block.splitlines()

    assert lines[0].startswith("┌─ RENDER FAILED ") and lines[0].endswith("· worker ┐")
    assert lines[-1].startswith("└") and lines[-1].endswith("┘")
    assert {len(line) for line in lines} == {activity_console._WIDTH}
    assert all(line.startswith("│") and line.endswith("│") for line in lines[1:-1])
    text = "\n".join(lines)
    assert "4ae8067c-6ebf-4131-b816-1fb414480b9a" in text
    assert "line one" in text and "line two" in text and "…" in text
    assert "skip" not in text


def test_render_colour_wraps_every_line():
    block = activity_console.render({"kind": "video_completed", "ts": "0", "source": "worker"}, colour=True)
    assert all(line.startswith("\x1b[32m") and line.endswith("\x1b[0m") for line in block.splitlines())


async def test_console_prints_new_events(feed, monkeypatch):
    printed = []
    monkeypatch.setattr(activity_console._out, "info", printed.append)
    monkeypatch.setattr(activity_console, "_BLOCK_MS", 50)

    task = asyncio.create_task(activity_console.run())
    await asyncio.sleep(0.1)  # console is now reading from "$"
    activity.emit("video_completed", video_id="v9")
    for _ in range(50):
        if printed:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(printed) == 1
    assert "VIDEO COMPLETED" in printed[0] and "v9" in printed[0]
