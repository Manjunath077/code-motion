"""Sync repositories (used by Celery) follow the same rules as the async ones."""
import uuid

from app.db.models import Scene, Video
from app.repository import sync_scene_repository as scenes
from app.repository import sync_video_repository as videos
from app.schemas.status import SceneStatus, VideoStatus


def _seed(factory) -> tuple[uuid.UUID, uuid.UUID]:
    with factory() as session, session.begin():
        video = Video(user_prompt="p", status="created", current_stage="created")
        session.add(video)
        session.flush()
        scene = Scene(video_id=video.id, status="pending")
        session.add(scene)
        session.flush()
        return video.id, scene.id


def test_scene_status_does_not_change_video(sync_db):
    video_id, scene_id = _seed(sync_db)
    videos.update_video_status_sync(video_id, VideoStatus.FINAL_RENDER)

    assert scenes.update_scene_status_sync(scene_id, SceneStatus.FAILED, error_message="x") is True

    assert scenes.get_scene_sync(scene_id).status == SceneStatus.FAILED
    assert videos.get_video_sync(video_id).status == VideoStatus.FINAL_RENDER


def test_failed_video_keeps_current_stage(sync_db):
    video_id, _ = _seed(sync_db)
    videos.update_video_status_sync(video_id, VideoStatus.FINAL_RENDER)

    videos.update_video_status_sync(video_id, VideoStatus.FAILED, error_message="render died")

    video = videos.get_video_sync(video_id)
    assert video.status == VideoStatus.FAILED
    assert video.current_stage == VideoStatus.FINAL_RENDER
    assert video.error_message == "render died"


def test_update_fields(sync_db):
    video_id, scene_id = _seed(sync_db)

    scenes.update_scene_sync(scene_id, rendered_segment_url="/media/x.mp4")
    videos.update_video_sync(video_id, final_video_url="/media/x.mp4")

    assert scenes.get_scene_sync(scene_id).rendered_segment_url == "/media/x.mp4"
    assert videos.get_video_sync(video_id).final_video_url == "/media/x.mp4"


def test_unknown_ids(sync_db):
    assert scenes.get_scene_sync("bad") is None
    assert videos.get_video_sync(uuid.uuid4()) is None
    assert scenes.update_scene_status_sync(uuid.uuid4(), SceneStatus.FAILED) is False
    assert videos.update_video_status_sync("bad", VideoStatus.FAILED) is False
