from unittest.mock import AsyncMock, patch
from tests.integration.conftest import make_scene
from app.schemas.scene_schema import SceneStatus


# ── GET /scenes/ ──────────────────────────────────────────────────────────────

async def test_list_scenes_returns_200(client):
    scenes = [make_scene(), make_scene()]
    with patch("app.api.v1.routes.scenes.list_scenes", new_callable=AsyncMock, return_value=(scenes, 2)):
        resp = await client.get("/api/v1/scenes/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["scenes"]) == 2


async def test_list_scenes_empty(client):
    with patch("app.api.v1.routes.scenes.list_scenes", new_callable=AsyncMock, return_value=([], 0)):
        resp = await client.get("/api/v1/scenes/")

    assert resp.status_code == 200
    assert resp.json() == {"scenes": [], "total": 0}


# ── GET /scenes/{scene_id} ────────────────────────────────────────────────────

async def test_get_scene_found_returns_200(client):
    scene = make_scene(status=SceneStatus.COMPLETED, video_url="/media/abc/output.mp4")
    with patch("app.api.v1.routes.scenes.get_scene_by_id", new_callable=AsyncMock, return_value=scene):
        resp = await client.get(f"/api/v1/scenes/{scene.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == scene.id
    assert body["status"] == SceneStatus.COMPLETED
    assert body["video_url"] == "/media/abc/output.mp4"


async def test_get_scene_not_found_returns_404(client):
    with patch("app.api.v1.routes.scenes.get_scene_by_id", new_callable=AsyncMock, return_value=None):
        resp = await client.get("/api/v1/scenes/000000000000000000000000")

    assert resp.status_code == 404


# ── DELETE /scenes/{scene_id} ─────────────────────────────────────────────────

async def test_delete_scene_returns_204(client):
    with patch("app.api.v1.routes.scenes.delete_scene", new_callable=AsyncMock, return_value=True):
        resp = await client.delete("/api/v1/scenes/000000000000000000000000")

    assert resp.status_code == 204


async def test_delete_scene_not_found_returns_404(client):
    with patch("app.api.v1.routes.scenes.delete_scene", new_callable=AsyncMock, return_value=False):
        resp = await client.delete("/api/v1/scenes/000000000000000000000000")

    assert resp.status_code == 404


# ── POST /scenes/{scene_id}/regenerate ───────────────────────────────────────

async def test_regenerate_returns_202(client):
    scene = make_scene(status=SceneStatus.FAILED)
    with patch("app.api.v1.routes.scenes.get_scene_by_id", new_callable=AsyncMock, return_value=scene), \
         patch("app.api.v1.routes.scenes.update_scene_status", new_callable=AsyncMock), \
         patch("app.api.v1.routes.scenes.generate_and_queue", new_callable=AsyncMock):
        resp = await client.post(f"/api/v1/scenes/{scene.id}/regenerate")

    assert resp.status_code == 202
    body = resp.json()
    assert body["scene_id"] == scene.id
    assert body["status"] == SceneStatus.QUEUED


async def test_regenerate_not_found_returns_404(client):
    with patch("app.api.v1.routes.scenes.get_scene_by_id", new_callable=AsyncMock, return_value=None):
        resp = await client.post("/api/v1/scenes/000000000000000000000000/regenerate")

    assert resp.status_code == 404


async def test_regenerate_validation_failure_returns_422(client):
    from app.services.scene_service import ScriptValidationError
    scene = make_scene()
    with patch("app.api.v1.routes.scenes.get_scene_by_id", new_callable=AsyncMock, return_value=scene), \
         patch("app.api.v1.routes.scenes.update_scene_status", new_callable=AsyncMock), \
         patch(
             "app.api.v1.routes.scenes.generate_and_queue",
             new_callable=AsyncMock,
             side_effect=ScriptValidationError("banned import 'os'"),
         ):
        resp = await client.post(f"/api/v1/scenes/{scene.id}/regenerate")

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
