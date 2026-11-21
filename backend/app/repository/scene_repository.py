"""Scenes (async, for the API). Changing a scene's status never changes its
video's status: the pipeline sets each one explicitly."""
from typing import Optional

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.db.models import Scene, Video
from app.db.session import AsyncSessionLocal
from app.repository._common import SCENE_FIELDS, IdLike, apply_fields, as_uuid, set_scene_status
from app.schemas.api import SceneOut
from app.schemas.status import SceneStatus

logger = get_logger(__name__)


async def create_scene(video_id: IdLike, *, order: int = 0, **fields) -> Optional[SceneOut]:
    """New PENDING scene under a video. None if the video does not exist."""
    v_id = as_uuid(video_id)
    if v_id is None:
        return None
    async with AsyncSessionLocal() as session:
        async with session.begin():
            if await session.get(Video, v_id) is None:
                return None
            scene = Scene(video_id=v_id, order=order)
            apply_fields(scene, fields, SCENE_FIELDS)
            set_scene_status(scene, SceneStatus.PENDING)
            session.add(scene)
        logger.info("Scene created: %s (video %s)", scene.id, v_id)
        return SceneOut.model_validate(scene)


async def get_scene(scene_id: IdLike) -> Optional[SceneOut]:
    s_id = as_uuid(scene_id)
    if s_id is None:
        return None
    async with AsyncSessionLocal() as session:
        scene = await session.get(Scene, s_id)
        return SceneOut.model_validate(scene) if scene else None


async def list_scenes(
    video_id: IdLike = None, limit: int = 20, skip: int = 0
) -> tuple[list[SceneOut], int]:
    """Scenes of one video in order, or all scenes newest first."""
    query = select(Scene)
    count = select(func.count()).select_from(Scene)
    if video_id is not None:
        v_id = as_uuid(video_id)
        if v_id is None:
            return [], 0
        query = query.where(Scene.video_id == v_id).order_by(Scene.order)
        count = count.where(Scene.video_id == v_id)
    else:
        query = query.order_by(Scene.created_at.desc())

    async with AsyncSessionLocal() as session:
        total = await session.scalar(count)
        scenes = (await session.scalars(query.offset(skip).limit(limit))).all()
        return [SceneOut.model_validate(s) for s in scenes], total or 0


async def update_scene_status(scene_id: IdLike, status: SceneStatus, **fields) -> bool:
    """Set the scene's status (and optionally other fields). False if not found."""
    found = await _update(scene_id, status, fields)
    if found:
        logger.info("Scene %s status → %s", scene_id, SceneStatus(status).value)
    return found


async def update_scene(scene_id: IdLike, **fields) -> bool:
    """Set fields other than status. False if not found."""
    return await _update(scene_id, None, fields)


async def delete_scene(scene_id: IdLike) -> bool:
    """Delete one scene (and its attempts). The video is kept."""
    s_id = as_uuid(scene_id)
    if s_id is None:
        return False
    async with AsyncSessionLocal() as session:
        async with session.begin():
            scene = await session.get(Scene, s_id)
            if scene is None:
                return False
            await session.delete(scene)
    return True


async def _update(scene_id: IdLike, status: Optional[SceneStatus], fields: dict) -> bool:
    s_id = as_uuid(scene_id)
    if s_id is None:
        return False
    async with AsyncSessionLocal() as session:
        async with session.begin():
            scene = await session.get(Scene, s_id)
            if scene is None:
                return False
            apply_fields(scene, fields, SCENE_FIELDS)
            if status is not None:
                set_scene_status(scene, status)
    return True
