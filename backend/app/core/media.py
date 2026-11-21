"""Where a video's files live on disk and under which URL they are served.

    media/{video_id}/scenes/{scene_id}.mp4
"""
from pathlib import Path
from typing import Union
from uuid import UUID

from app.core.config import settings

Id = Union[str, UUID]


def video_media_dir(video_id: Id) -> Path:
    return Path(settings.MEDIA_DIR) / str(video_id)


def scene_media_path(video_id: Id, scene_id: Id) -> tuple[Path, str]:
    """(file on disk, public URL) of a scene's rendered mp4."""
    relative = f"{video_id}/scenes/{scene_id}.mp4"
    return Path(settings.MEDIA_DIR) / relative, f"/media/{relative}"
