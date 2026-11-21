from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from tests.integration.conftest import make_scene, make_video
from app.schemas.status import SceneStatus, VideoStatus

ROUTE = "app.api.v1.routes.prompt"


@contextmanager
def pipeline(generate_side_effect=None):
    """Patch the route's repositories and pipeline; yields the mocks."""
    video = make_video()
    scene = make_scene(status=SceneStatus.APPROVED, video_id=video.id)
    queued = make_video(status=VideoStatus.FINAL_RENDER, id=video.id, scenes=[scene])
    with patch(f"{ROUTE}.create_video", new_callable=AsyncMock, return_value=video) as create_video, \
         patch(f"{ROUTE}.create_scene", new_callable=AsyncMock, return_value=scene), \
         patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=queued), \
         patch(f"{ROUTE}.generate_and_queue", new_callable=AsyncMock, side_effect=generate_side_effect) as gen:
        yield {"video": video, "scene": scene, "create_video": create_video, "generate": gen}


async def test_post_prompt_returns_202_with_video_and_scene(client):
    with pipeline() as m:
        resp = await client.post("/api/v1/prompt/", json={"prompt": "animate bubble sort"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == str(m["video"].id)
    assert body["status"] == VideoStatus.FINAL_RENDER
    assert body["scenes"][0]["id"] == str(m["scene"].id)
    assert body["scenes"][0]["status"] == SceneStatus.APPROVED
    m["generate"].assert_awaited_once_with(str(m["video"].id), str(m["scene"].id), "animate bubble sort")


async def test_post_prompt_passes_review_mode(client):
    with pipeline() as m:
        await client.post("/api/v1/prompt/", json={"prompt": "p", "review_mode": False})

    m["create_video"].assert_awaited_once_with("p", review_mode=False)


async def test_post_prompt_too_long_returns_422(client):
    resp = await client.post("/api/v1/prompt/", json={"prompt": "x" * 2001})
    assert resp.status_code == 422


async def test_post_prompt_empty_body_returns_422(client):
    resp = await client.post("/api/v1/prompt/", json={})
    assert resp.status_code == 422


async def test_post_prompt_empty_string_returns_422(client):
    resp = await client.post("/api/v1/prompt/", json={"prompt": ""})
    assert resp.status_code == 422


async def test_post_prompt_validation_failure_returns_422(client):
    from app.services.scene_service import ScriptValidationError

    with pipeline(ScriptValidationError("banned import 'os'")):
        resp = await client.post("/api/v1/prompt/", json={"prompt": "import os"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "os" in body["detail"]


async def test_post_prompt_llm_error_returns_500(client):
    with pipeline(RuntimeError("OpenRouter down")):
        resp = await client.post("/api/v1/prompt/", json={"prompt": "animate something"})

    assert resp.status_code == 500
