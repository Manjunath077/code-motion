from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from tests.integration.conftest import make_scene, make_video
from app.pipeline.transitions import QueueUnavailable
from app.schemas.status import VideoStatus

ROUTE = "app.api.v1.routes.videos"


# ── POST /videos ──────────────────────────────────────────────────────────────

async def test_create_returns_202_without_calling_the_llm(client):
    """Hard rule 5: no LLM call inside an HTTP request."""
    video = make_video()
    queued = make_video(status=VideoStatus.CODEGEN, id=video.id)
    with patch(f"{ROUTE}.create_video", new_callable=AsyncMock, return_value=video), \
         patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=queued), \
         patch("app.pipeline.transitions.transition_video_status", new_callable=AsyncMock, return_value=True), \
         patch("app.pipeline.transitions.enqueue_stage", new_callable=MagicMock) as enqueue, \
         patch("app.core.model_router.call_text", new_callable=AsyncMock) as llm:
        resp = await client.post("/api/v1/videos", json={"prompt": "explain heap sort"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"] == str(video.id)
    assert body["status"] == VideoStatus.CODEGEN
    enqueue.assert_called_once_with(video.id, VideoStatus.CODEGEN)
    llm.assert_not_awaited()


async def test_create_passes_review_mode(client):
    video = make_video()
    with patch(f"{ROUTE}.create_video", new_callable=AsyncMock, return_value=video) as create, \
         patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=video), \
         patch(f"{ROUTE}.start", new_callable=AsyncMock):
        await client.post("/api/v1/videos", json={"prompt": "p", "review_mode": False})

    create.assert_awaited_once_with("p", review_mode=False)


async def test_create_queue_down_returns_503(client):
    with patch(f"{ROUTE}.create_video", new_callable=AsyncMock, return_value=make_video()), \
         patch(f"{ROUTE}.start", new_callable=AsyncMock, side_effect=QueueUnavailable("redis down")):
        resp = await client.post("/api/v1/videos", json={"prompt": "p"})

    assert resp.status_code == 503


async def test_create_validates_prompt(client):
    for body in ({}, {"prompt": ""}, {"prompt": "x" * 2001}):
        resp = await client.post("/api/v1/videos", json=body)
        assert resp.status_code == 422, body


# ── GET ───────────────────────────────────────────────────────────────────────

async def test_list_videos(client):
    videos = [make_video(), make_video()]
    with patch(f"{ROUTE}.list_videos", new_callable=AsyncMock, return_value=(videos, 2)):
        resp = await client.get("/api/v1/videos")

    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    assert len(resp.json()["videos"]) == 2


async def test_get_video_with_scenes(client):
    video = make_video(status=VideoStatus.COMPLETED)
    video.scenes.append(make_scene(video_id=video.id))
    with patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=video):
        resp = await client.get(f"/api/v1/videos/{video.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == VideoStatus.COMPLETED
    assert body["scenes"][0]["video_id"] == str(video.id)


async def test_get_video_not_found(client):
    with patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=None):
        resp = await client.get(f"/api/v1/videos/{uuid4()}")
    assert resp.status_code == 404


async def test_get_video_bad_id_is_422(client):
    resp = await client.get("/api/v1/videos/not-a-uuid")
    assert resp.status_code == 422


# ── resume ────────────────────────────────────────────────────────────────────

async def test_resume_failed_video_returns_202(client):
    failed = make_video(status=VideoStatus.FAILED, current_stage=VideoStatus.CODEGEN)
    resumed = make_video(status=VideoStatus.CODEGEN, id=failed.id)
    with patch(f"{ROUTE}.get_video", new_callable=AsyncMock, side_effect=[failed, resumed]), \
         patch(f"{ROUTE}.runner.resume", new_callable=AsyncMock, return_value=True) as resume:
        resp = await client.post(f"/api/v1/videos/{failed.id}/resume")

    assert resp.status_code == 202
    assert resp.json()["status"] == VideoStatus.CODEGEN
    resume.assert_awaited_once_with(failed.id)


async def test_resume_running_video_is_409(client):
    with patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=make_video(status=VideoStatus.CODEGEN)):
        resp = await client.post(f"/api/v1/videos/{uuid4()}/resume")
    assert resp.status_code == 409


async def test_resume_stuck_running_video_kicks_it(client):
    from datetime import datetime, timedelta, timezone
    long_ago = datetime.now(timezone.utc) - timedelta(days=1)
    stuck = make_video(status=VideoStatus.CODEGEN, updated_at=long_ago)
    with patch(f"{ROUTE}.get_video", new_callable=AsyncMock, side_effect=[stuck, stuck]),          patch(f"{ROUTE}.runner.kick", new_callable=AsyncMock, return_value=True) as kick:
        resp = await client.post(f"/api/v1/videos/{stuck.id}/resume")

    assert resp.status_code == 202
    kick.assert_awaited_once_with(stuck.id, VideoStatus.CODEGEN)


async def test_resume_not_found(client):
    with patch(f"{ROUTE}.get_video", new_callable=AsyncMock, return_value=None):
        resp = await client.post(f"/api/v1/videos/{uuid4()}/resume")
    assert resp.status_code == 404


# ── DELETE ────────────────────────────────────────────────────────────────────

async def test_delete_removes_media_folder(client, tmp_path, monkeypatch):
    video_id = uuid4()
    monkeypatch.setattr("app.core.media.settings.MEDIA_DIR", str(tmp_path))
    folder = tmp_path / str(video_id) / "scenes"
    folder.mkdir(parents=True)
    (folder / "s.mp4").write_bytes(b"mp4")

    with patch(f"{ROUTE}.delete_video", new_callable=AsyncMock, return_value=True):
        resp = await client.delete(f"/api/v1/videos/{video_id}")

    assert resp.status_code == 204
    assert not (tmp_path / str(video_id)).exists()


async def test_delete_not_found(client):
    with patch(f"{ROUTE}.delete_video", new_callable=AsyncMock, return_value=False):
        resp = await client.delete(f"/api/v1/videos/{uuid4()}")
    assert resp.status_code == 404
