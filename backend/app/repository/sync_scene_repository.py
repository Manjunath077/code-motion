from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.db.models import Scene, Video
from app.db.sync_session import SessionLocal
from app.schemas.scene_schema import SceneDocument, SceneStatus
from app.core.logging import get_logger

logger = get_logger(__name__)


def _row_to_scene(video: Video, scene: Scene) -> SceneDocument:
    return SceneDocument(
        id=str(scene.id),
        prompt=video.user_prompt,
        generated_script=scene.generated_script,
        status=SceneStatus(scene.status),
        video_url=scene.rendered_segment_url,
        error_message=scene.error_message,
        created_at=video.created_at,
        updated_at=scene.updated_at,
    )


def get_scene_by_id_sync(scene_id: str) -> Optional[SceneDocument]:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return None

    with SessionLocal() as session:
        scene = session.get(Scene, s_id)
        if scene is None:
            return None
        video = session.get(Video, scene.video_id)
        if video is None:
            return None
        return _row_to_scene(video, scene)


def update_scene_status_sync(scene_id: str, status: SceneStatus, **kwargs) -> None:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return

    with SessionLocal() as session:
        scene = session.get(Scene, s_id)
        if scene is None:
            return

        now = datetime.now(timezone.utc)
        scene.status = status.value
        scene.updated_at = now
        if "error_message" in kwargs:
            scene.error_message = kwargs["error_message"]

        video = session.get(Video, scene.video_id)
        if video is not None:
            video.status = status.value
            video.updated_at = now
            if "error_message" in kwargs:
                video.error_message = kwargs["error_message"]

        session.commit()

    logger.info("Scene %s status → %s", scene_id, status)


def update_scene_video_sync(scene_id: str, video_url: str) -> None:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return

    with SessionLocal() as session:
        scene = session.get(Scene, s_id)
        if scene is None:
            return
        scene.rendered_segment_url = video_url
        scene.updated_at = datetime.now(timezone.utc)
        session.commit()
