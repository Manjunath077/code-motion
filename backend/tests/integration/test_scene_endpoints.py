from unittest.mock import AsyncMock, patch
from uuid import uuid4

from tests.integration.conftest import make_scene, make_video
from app.schemas.status import SceneStatus

ROUTE = "app.api.v1.routes.scenes"


# ── GET /scenes/ ──────────────────────────────────────────────────────────────

async def test_list_scenes_returns_200(client):
    scenes = [make_scene(), make_scene()]
    with patch(f"{ROUTE}.list_scenes", new_callable=AsyncMock, return_value=(scenes, 2)):
        resp = await client.get("/api/v1/scenes/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["scenes"]) == 2


async def test_list_scenes_empty(client):
    with patch(f"{ROUTE}.list_scenes", new_callable=AsyncMock, return_value=([], 0)):
        resp = await client.get("/api/v1/scenes/")

    assert resp.status_code == 200
    assert resp.json() == {"scenes": [], "total": 0}


# ── GET /scenes/{scene_id} ────────────────────────────────────────────────────

async def test_get_scene_found_returns_200(client):
    scene = make_scene(status=SceneStatus.RENDERED, rendered_segment_url="/media/v/scenes/s.mp4")
    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, return_value=scene):
        resp = await client.get(f"/api/v1/scenes/{scene.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(scene.id)
    assert body["video_id"] == str(scene.video_id)
    assert body["status"] == SceneStatus.RENDERED
    assert body["rendered_segment_url"] == "/media/v/scenes/s.mp4"


async def test_get_scene_not_found_returns_404(client):
    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, return_value=None):
        resp = await client.get(f"/api/v1/scenes/{uuid4()}")

    assert resp.status_code == 404


# ── DELETE /scenes/{scene_id} ─────────────────────────────────────────────────

async def test_delete_scene_returns_204_and_removes_file(client, tmp_path, monkeypatch):
    scene = make_scene()
    monkeypatch.setattr("app.workers.render_task.settings.MEDIA_DIR", str(tmp_path))
    media = tmp_path / str(scene.video_id) / "scenes" / f"{scene.id}.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"mp4")

    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, return_value=scene), \
         patch(f"{ROUTE}.delete_scene", new_callable=AsyncMock, return_value=True):
        resp = await client.delete(f"/api/v1/scenes/{scene.id}")

    assert resp.status_code == 204
    assert not media.exists()


async def test_delete_scene_not_found_returns_404(client):
    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, return_value=None):
        resp = await client.delete(f"/api/v1/scenes/{uuid4()}")

    assert resp.status_code == 404


# ── POST /scenes/{scene_id}/regenerate ───────────────────────────────────────

async def test_regenerate_returns_202_and_uses_video_prompt(client):
    video = make_video(user_prompt="explain heap sort")
    scene = make_scene(status=SceneStatus.FAILED, video_id=video.id)
    requeued = make_scene(status=SceneStatus.APPROVED, id=scene.id, video_id=video.id)

    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, side_effect=[scene, requeued]), \
         patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=video), \
         patch(f"{ROUTE}.update_scene_status", new_callable=AsyncMock) as reset, \
         patch(f"{ROUTE}.generate_and_queue", new_callable=AsyncMock) as gen:
        resp = await client.post(f"/api/v1/scenes/{scene.id}/regenerate")

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == str(scene.id)
    assert body["status"] == SceneStatus.APPROVED
    assert reset.await_args.args[1] == SceneStatus.PENDING
    gen.assert_awaited_once_with(str(video.id), str(scene.id), "explain heap sort")


async def test_regenerate_not_found_returns_404(client):
    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, return_value=None):
        resp = await client.post(f"/api/v1/scenes/{uuid4()}/regenerate")

    assert resp.status_code == 404


async def test_regenerate_validation_failure_returns_422(client):
    from app.services.scene_service import ScriptValidationError

    video = make_video()
    scene = make_scene(video_id=video.id)
    with patch(f"{ROUTE}.get_scene", new_callable=AsyncMock, return_value=scene), \
         patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=video), \
         patch(f"{ROUTE}.update_scene_status", new_callable=AsyncMock), \
         patch(
             f"{ROUTE}.generate_and_queue",
             new_callable=AsyncMock,
             side_effect=ScriptValidationError("banned import 'os'"),
         ):
        resp = await client.post(f"/api/v1/scenes/{scene.id}/regenerate")

    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"
