from unittest.mock import AsyncMock, patch
from tests.integration.conftest import make_scene
from app.schemas.scene_schema import SceneStatus


async def test_post_prompt_returns_202_with_scene_id(client):
    scene = make_scene(status=SceneStatus.QUEUED)

    with patch("app.api.v1.routes.prompt.create_scene", new_callable=AsyncMock, return_value=scene), \
         patch("app.api.v1.routes.prompt.generate_and_queue", new_callable=AsyncMock):
        resp = await client.post("/api/v1/prompt/", json={"prompt": "animate bubble sort"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["scene_id"] == scene.id
    assert body["status"] == SceneStatus.QUEUED


async def test_post_prompt_too_long_returns_422(client):
    resp = await client.post("/api/v1/prompt/", json={"prompt": "x" * 2001})
    assert resp.status_code == 422


async def test_post_prompt_empty_body_returns_422(client):
    resp = await client.post("/api/v1/prompt/", json={})
    assert resp.status_code == 422


async def test_post_prompt_validation_failure_returns_422(client):
    from app.services.scene_service import ScriptValidationError
    scene = make_scene(status=SceneStatus.FAILED)

    with patch("app.api.v1.routes.prompt.create_scene", new_callable=AsyncMock, return_value=scene), \
         patch(
             "app.api.v1.routes.prompt.generate_and_queue",
             new_callable=AsyncMock,
             side_effect=ScriptValidationError("banned import 'os'"),
         ):
        resp = await client.post("/api/v1/prompt/", json={"prompt": "import os"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "os" in body["detail"]


async def test_post_prompt_llm_error_returns_500(client):
    scene = make_scene(status=SceneStatus.FAILED)

    with patch("app.api.v1.routes.prompt.create_scene", new_callable=AsyncMock, return_value=scene), \
         patch(
             "app.api.v1.routes.prompt.generate_and_queue",
             new_callable=AsyncMock,
             side_effect=RuntimeError("OpenAI down"),
         ):
        resp = await client.post("/api/v1/prompt/", json={"prompt": "animate something"})

    assert resp.status_code == 500
