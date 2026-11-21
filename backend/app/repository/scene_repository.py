from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from app.db.models import Scene, Video
from app.db.session import AsyncSessionLocal
from app.schemas.scene_schema import SceneDocument, SceneStatus
from app.core.logging import get_logger

logger = get_logger(__name__)

# Temporary: a strict one-Scene-per-Video pairing so the existing flat
# SceneDocument API shape needs no changes. This ends in NEW_PLAN.md step 4,
# when the repositories are split and video/scene statuses are decoupled.

_SCENE_FIELD_MAP = {
    "generated_script": "generated_script",
    "video_url": "rendered_segment_url",
    "error_message": "error_message",
}


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


async def create_scene(prompt: str) -> SceneDocument:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            video = Video(user_prompt=prompt, status=SceneStatus.PENDING.value, created_at=now, updated_at=now)
            session.add(video)
            await session.flush()

            scene = Scene(
                video_id=video.id,
                order=0,
                status=SceneStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
            session.add(scene)
            await session.flush()

        logger.info("Scene created: %s", scene.id)
        return _row_to_scene(video, scene)


async def get_scene_by_id(scene_id: str) -> Optional[SceneDocument]:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Scene, Video).join(Video, Scene.video_id == Video.id).where(Scene.id == s_id)
        )
        row = result.first()

    if row is None:
        return None
    scene, video = row
    return _row_to_scene(video, scene)


async def list_scenes(limit: int = 20, skip: int = 0) -> tuple[list[SceneDocument], int]:
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Video))
        result = await session.execute(
            select(Scene, Video)
            .join(Video, Scene.video_id == Video.id)
            .order_by(Video.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = result.all()

    scenes = [_row_to_scene(video, scene) for scene, video in rows]
    return scenes, total or 0


async def update_scene_status(scene_id: str, status: SceneStatus, **kwargs) -> None:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return

    async with AsyncSessionLocal() as session:
        async with session.begin():
            scene = await session.get(Scene, s_id)
            if scene is None:
                return

            now = datetime.now(timezone.utc)
            scene.status = status.value
            scene.updated_at = now
            for key, value in kwargs.items():
                setattr(scene, _SCENE_FIELD_MAP.get(key, key), value)

            video = await session.get(Video, scene.video_id)
            if video is not None:
                video.status = status.value
                video.updated_at = now
                if "error_message" in kwargs:
                    video.error_message = kwargs["error_message"]

    logger.info("Scene %s status → %s", scene_id, status)


async def delete_scene(scene_id: str) -> bool:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return False

    async with AsyncSessionLocal() as session:
        async with session.begin():
            scene = await session.get(Scene, s_id)
            if scene is None:
                return False

            video = await session.get(Video, scene.video_id)
            if video is not None:
                await session.delete(video)  # cascades to the scene row
            else:
                await session.delete(scene)

    return True


async def update_scene_script(scene_id: str, script: str) -> None:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return

    async with AsyncSessionLocal() as session:
        async with session.begin():
            scene = await session.get(Scene, s_id)
            if scene is None:
                return
            scene.generated_script = script
            scene.updated_at = datetime.now(timezone.utc)


async def update_scene_video(scene_id: str, video_url: str) -> None:
    try:
        s_id = UUID(scene_id)
    except ValueError:
        return

    async with AsyncSessionLocal() as session:
        async with session.begin():
            scene = await session.get(Scene, s_id)
            if scene is None:
                return
            scene.rendered_segment_url = video_url
            scene.updated_at = datetime.now(timezone.utc)
