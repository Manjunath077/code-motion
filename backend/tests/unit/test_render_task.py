"""Render task + FINAL_RENDER fan-in (sync, as in the Celery worker)."""
import uuid
from unittest.mock import MagicMock

import pytest

import app.workers.render_task as render_task
from app.db.models import Scene, Video
from app.pipeline import transitions
from app.repository import sync_scene_repository as scenes
from app.repository import sync_video_repository as videos
from app.schemas.status import SceneStatus, VideoStatus


@pytest.fixture
def enqueue(monkeypatch):
    m = MagicMock()
    monkeypatch.setattr(transitions, "enqueue_stage", m)
    return m


def _seed(factory, scene_statuses, video_status="final_render"):
    with factory() as session, session.begin():
        video = Video(user_prompt="p", status=video_status, current_stage=video_status)
        session.add(video)
        session.flush()
        ids = []
        for order, status in enumerate(scene_statuses):
            scene = Scene(video_id=video.id, order=order, status=status, generated_script="s")
            session.add(scene)
            session.flush()
            ids.append(scene.id)
        return video.id, ids


# ── fan-in ────────────────────────────────────────────────────────────────────

def test_last_rendered_scene_advances_video(sync_db, enqueue):
    video_id, _ = _seed(sync_db, ["rendered", "rendered"])

    transitions.scene_render_finished_sync(video_id)

    assert videos.get_video_sync(video_id).status == VideoStatus.ASSEMBLE
    enqueue.assert_called_once_with(video_id, VideoStatus.ASSEMBLE)


def test_scene_still_rendering_does_not_advance(sync_db, enqueue):
    video_id, _ = _seed(sync_db, ["rendered", "approved"])

    transitions.scene_render_finished_sync(video_id)

    assert videos.get_video_sync(video_id).status == VideoStatus.FINAL_RENDER
    enqueue.assert_not_called()


def test_failed_scene_fails_video(sync_db, enqueue):
    video_id, _ = _seed(sync_db, ["rendered", "failed"])

    transitions.scene_render_finished_sync(video_id)

    video = videos.get_video_sync(video_id)
    assert video.status == VideoStatus.FAILED
    assert video.current_stage == VideoStatus.FINAL_RENDER
    assert "Scene 1" in video.error_message
    enqueue.assert_not_called()


def test_fan_in_ignores_video_not_at_final_render(sync_db, enqueue):
    video_id, _ = _seed(sync_db, ["rendered"], video_status="failed")

    transitions.scene_render_finished_sync(video_id)

    assert videos.get_video_sync(video_id).status == VideoStatus.FAILED
    enqueue.assert_not_called()


def test_second_fan_in_call_does_not_enqueue_again(sync_db, enqueue):
    video_id, _ = _seed(sync_db, ["rendered"])

    transitions.scene_render_finished_sync(video_id)
    transitions.scene_render_finished_sync(video_id)

    assert enqueue.call_count == 1


# ── render task ───────────────────────────────────────────────────────────────

def test_render_success_marks_rendered_and_advances(sync_db, enqueue, monkeypatch):
    video_id, (scene_id,) = _seed(sync_db, ["approved"])
    monkeypatch.setattr(render_task, "_render", MagicMock(return_value="/media/v/scenes/s.mp4"))

    render_task.render_scene(str(scene_id))

    scene = scenes.get_scene_sync(scene_id)
    assert scene.status == SceneStatus.RENDERED
    assert scene.rendered_segment_url == "/media/v/scenes/s.mp4"
    assert videos.get_video_sync(video_id).status == VideoStatus.ASSEMBLE


def test_render_failure_marks_scene_and_video_failed(sync_db, enqueue, monkeypatch):
    video_id, (scene_id,) = _seed(sync_db, ["approved"])
    monkeypatch.setattr(render_task, "_render", MagicMock(side_effect=RuntimeError("LaTeX error")))

    render_task.render_scene(str(scene_id))

    assert scenes.get_scene_sync(scene_id).error_message == "LaTeX error"
    assert videos.get_video_sync(video_id).status == VideoStatus.FAILED


def test_render_missing_scene_is_a_noop(sync_db, enqueue):
    render_task.render_scene(str(uuid.uuid4()))
    enqueue.assert_not_called()
