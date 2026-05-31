import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from bson import ObjectId

from app.main import app
from app.schemas.scene_schema import SceneStatus


def make_scene(status=SceneStatus.QUEUED, **kwargs):
    from app.schemas.scene_schema import SceneDocument
    defaults = dict(
        id=str(ObjectId()),
        prompt="test prompt",
        generated_script="from manim import *\nclass S(Scene):\n    def construct(self): pass",
        status=status,
        video_url=None,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return SceneDocument(**defaults)


@pytest.fixture
async def client():
    """AsyncClient wired to the FastAPI app with DB lifecycle mocked out."""
    with patch("app.main.connect_db", new_callable=AsyncMock), \
         patch("app.main.close_db", new_callable=AsyncMock):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
