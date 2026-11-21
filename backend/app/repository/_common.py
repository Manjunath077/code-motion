"""Helpers shared by the async (API) and sync (Celery) repositories, so both
apply exactly the same rules."""
from typing import Any, Iterable, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from app.db.models import Scene, Video
from app.schemas.status import VIDEO_HALT_STATUSES, SceneStatus, VideoStatus

IdLike = Union[str, UUID, None]

# Columns callers may set through update_video / update_scene. status and
# current_stage are excluded: they only change through the *_status functions.
VIDEO_FIELDS = frozenset({
    "title", "review_mode", "approved_at", "spec", "outline", "storyboard_version",
    "verified_trace", "style_guide", "final_video_url", "final_audio_url",
    "duration_seconds", "error_message",
})
SCENE_FIELDS = frozenset({
    "order", "storyboard", "narration_text", "narration_audio_url",
    "narration_duration_seconds", "visual_description", "generated_script",
    "qa_report", "audio_hash", "code_hash", "preview_url", "rendered_segment_url",
    "error_message",
})


def as_uuid(value: IdLike) -> Optional[UUID]:
    """Parse an id; None for anything that is not a valid UUID."""
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None


def apply_fields(row: Any, fields: dict, allowed: frozenset) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"{type(row).__name__}: cannot set {sorted(unknown)}")
    for key, value in fields.items():
        # Artifacts (Spec, Outline, Storyboard, QAReport, ...) are stored as JSON.
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        setattr(row, key, value)


def set_video_status(video: Video, status: VideoStatus) -> None:
    """FAILED / WAITING_QUOTA keep current_stage, so the runner knows where to resume."""
    status = VideoStatus(status)
    video.status = status.value
    if status not in VIDEO_HALT_STATUSES:
        video.current_stage = status.value


def set_scene_status(scene: Scene, status: SceneStatus) -> None:
    scene.status = SceneStatus(status).value


def transition_values(to_status: VideoStatus, fields: dict) -> dict:
    """Column values for a compare-and-set status UPDATE (same rules as
    apply_fields + set_video_status)."""
    unknown = set(fields) - VIDEO_FIELDS
    if unknown:
        raise ValueError(f"Video: cannot set {sorted(unknown)}")
    values = {
        k: v.model_dump(mode="json") if isinstance(v, BaseModel) else v
        for k, v in fields.items()
    }
    to_status = VideoStatus(to_status)
    values["status"] = to_status.value
    if to_status not in VIDEO_HALT_STATUSES:
        values["current_stage"] = to_status.value
    return values


def status_values(from_status: Union[VideoStatus, Iterable[VideoStatus]]) -> list[str]:
    if isinstance(from_status, (str, VideoStatus)):
        from_status = [from_status]
    return [VideoStatus(s).value for s in from_status]
