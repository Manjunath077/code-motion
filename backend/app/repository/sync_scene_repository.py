"""Scenes (sync, for Celery workers). Same rules as scene_repository."""
from typing import Optional

from app.core.logging import get_logger
from app.db.models import Scene
from app.db.sync_session import SessionLocal
from app.repository._common import SCENE_FIELDS, IdLike, apply_fields, as_uuid, set_scene_status
from app.schemas.api import SceneOut
from app.schemas.status import SceneStatus

logger = get_logger(__name__)


def get_scene_sync(scene_id: IdLike) -> Optional[SceneOut]:
    s_id = as_uuid(scene_id)
    if s_id is None:
        return None
    with SessionLocal() as session:
        scene = session.get(Scene, s_id)
        return SceneOut.model_validate(scene) if scene else None


def update_scene_status_sync(scene_id: IdLike, status: SceneStatus, **fields) -> bool:
    found = _update(scene_id, status, fields)
    if found:
        logger.info("Scene %s status → %s", scene_id, SceneStatus(status).value)
    return found


def update_scene_sync(scene_id: IdLike, **fields) -> bool:
    return _update(scene_id, None, fields)


def _update(scene_id: IdLike, status: Optional[SceneStatus], fields: dict) -> bool:
    s_id = as_uuid(scene_id)
    if s_id is None:
        return False
    with SessionLocal() as session:
        with session.begin():
            scene = session.get(Scene, s_id)
            if scene is None:
                return False
            apply_fields(scene, fields, SCENE_FIELDS)
            if status is not None:
                set_scene_status(scene, status)
    return True
