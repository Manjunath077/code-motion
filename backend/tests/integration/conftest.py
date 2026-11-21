import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from app.main import app
from app.schemas.api import SceneOut, VideoOut
from app.schemas.status import SceneStatus, VideoStatus


def make_scene(status=SceneStatus.APPROVED, **kwargs) -> SceneOut:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        video_id=uuid4(),
        order=0,
        status=status,
        generated_script="from manim import *\nclass S(Scene):\n    def construct(self): pass",
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return SceneOut(**defaults)


def make_video(status=VideoStatus.CREATED, scenes=None, **kwargs) -> VideoOut:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid4(),
        user_prompt="test prompt",
        status=status,
        current_stage=status,
        review_mode=True,
        storyboard_version=0,
        created_at=now,
        updated_at=now,
        scenes=scenes or [],
    )
    defaults.update(kwargs)
    return VideoOut(**defaults)


@pytest.fixture
async def client():
    """AsyncClient wired to the FastAPI app with DB lifecycle mocked out."""
    with patch("app.main.connect_db", new_callable=AsyncMock), \
         patch("app.main.close_db", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
