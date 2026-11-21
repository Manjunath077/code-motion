"""Videos (sync, for Celery workers). Same rules as video_repository."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models import Video
from app.db.sync_session import SessionLocal
from app.repository._common import VIDEO_FIELDS, IdLike, apply_fields, as_uuid, set_video_status
from app.schemas.api import VideoOut
from app.schemas.status import VideoStatus

logger = get_logger(__name__)


def get_video_sync(video_id: IdLike) -> Optional[VideoOut]:
    v_id = as_uuid(video_id)
    if v_id is None:
        return None
    with SessionLocal() as session:
        video = session.scalar(
            select(Video).options(selectinload(Video.scenes)).where(Video.id == v_id)
        )
        return VideoOut.model_validate(video) if video else None


def update_video_status_sync(video_id: IdLike, status: VideoStatus, **fields) -> bool:
    found = _update(video_id, status, fields)
    if found:
        logger.info("Video %s status → %s", video_id, VideoStatus(status).value)
    return found


def update_video_sync(video_id: IdLike, **fields) -> bool:
    return _update(video_id, None, fields)


def _update(video_id: IdLike, status: Optional[VideoStatus], fields: dict) -> bool:
    v_id = as_uuid(video_id)
    if v_id is None:
        return False
    with SessionLocal() as session:
        with session.begin():
            video = session.get(Video, v_id)
            if video is None:
                return False
            apply_fields(video, fields, VIDEO_FIELDS)
            if status is not None:
                set_video_status(video, status)
    return True
