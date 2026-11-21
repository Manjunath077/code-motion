"""Videos (async, for the API). Changing a video never touches its scenes'
statuses, and vice versa."""
from datetime import datetime
from typing import Iterable, Optional, Union
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models import Video
from app.db.session import AsyncSessionLocal
from app.repository._common import (
    VIDEO_FIELDS, IdLike, apply_fields, as_uuid, set_video_status, status_values, transition_values,
)
from app.schemas.api import VideoOut
from app.schemas.status import VideoStatus

logger = get_logger(__name__)


async def create_video(user_prompt: str, *, review_mode: bool = True) -> VideoOut:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            video = Video(user_prompt=user_prompt, review_mode=review_mode, scenes=[])
            set_video_status(video, VideoStatus.CREATED)
            session.add(video)
        logger.info("Video created: %s", video.id)
        return VideoOut.model_validate(video)


async def get_video(video_id: IdLike) -> Optional[VideoOut]:
    v_id = as_uuid(video_id)
    if v_id is None:
        return None
    async with AsyncSessionLocal() as session:
        video = await session.scalar(
            select(Video).options(selectinload(Video.scenes)).where(Video.id == v_id)
        )
        return VideoOut.model_validate(video) if video else None


async def list_videos(limit: int = 20, skip: int = 0) -> tuple[list[VideoOut], int]:
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Video))
        videos = (
            await session.scalars(
                select(Video)
                .options(selectinload(Video.scenes))
                .order_by(Video.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [VideoOut.model_validate(v) for v in videos], total or 0


async def update_video_status(video_id: IdLike, status: VideoStatus, **fields) -> bool:
    """Set the video's status (and optionally other fields). False if not found."""
    found = await _update(video_id, status, fields)
    if found:
        logger.info("Video %s status → %s", video_id, VideoStatus(status).value)
    return found


async def update_video(video_id: IdLike, **fields) -> bool:
    """Set fields other than status. False if not found."""
    return await _update(video_id, None, fields)


async def transition_video_status(
    video_id: IdLike,
    from_status: Union[VideoStatus, Iterable[VideoStatus]],
    to_status: VideoStatus,
    **fields,
) -> bool:
    """Atomically move the video to to_status only if its status is still
    from_status (one status or several). True if this call made the change.
    Two workers racing to advance the same video: exactly one wins."""
    v_id = as_uuid(video_id)
    if v_id is None:
        return False
    stmt = (
        update(Video)
        .where(Video.id == v_id, Video.status.in_(status_values(from_status)))
        .values(**transition_values(to_status, fields))
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            changed = (await session.execute(stmt)).rowcount == 1
    if changed:
        logger.info("Video %s status → %s", video_id, VideoStatus(to_status).value)
    return changed


async def list_stale_videos(
    statuses: Iterable[VideoStatus], updated_before: datetime, limit: int = 100
) -> list[tuple[UUID, VideoStatus]]:
    """(id, status) of videos in one of `statuses` whose row has not changed
    since `updated_before`, oldest first."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Video.id, Video.status)
                .where(Video.status.in_(status_values(statuses)), Video.updated_at < updated_before)
                .order_by(Video.updated_at)
                .limit(limit)
            )
        ).all()
    return [(video_id, VideoStatus(status)) for video_id, status in rows]


async def delete_video(video_id: IdLike) -> bool:
    """Delete the video; its scenes, attempts and events cascade."""
    v_id = as_uuid(video_id)
    if v_id is None:
        return False
    async with AsyncSessionLocal() as session:
        async with session.begin():
            video = await session.get(Video, v_id)
            if video is None:
                return False
            await session.delete(video)
    return True


async def _update(video_id: IdLike, status: Optional[VideoStatus], fields: dict) -> bool:
    v_id = as_uuid(video_id)
    if v_id is None:
        return False
    async with AsyncSessionLocal() as session:
        async with session.begin():
            video = await session.get(Video, v_id)
            if video is None:
                return False
            apply_fields(video, fields, VIDEO_FIELDS)
            if status is not None:
                set_video_status(video, status)
    return True
