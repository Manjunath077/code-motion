"""HTTP request/response shapes."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.artifacts import Outline, QAReport, Spec, Storyboard
from app.schemas.status import SceneStatus, VideoStatus


class VideoCreate(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    review_mode: bool = True


class SceneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    video_id: UUID
    order: int
    status: SceneStatus
    storyboard: Optional[Storyboard] = None
    generated_script: Optional[str] = None
    preview_url: Optional[str] = None
    rendered_segment_url: Optional[str] = None
    qa_report: Optional[QAReport] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_prompt: str
    title: Optional[str] = None
    status: VideoStatus
    current_stage: Optional[VideoStatus] = None
    review_mode: bool
    storyboard_version: int
    approved_at: Optional[datetime] = None
    spec: Optional[Spec] = None
    outline: Optional[Outline] = None
    final_video_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    scenes: list[SceneOut] = Field(default_factory=list)


class SceneListOut(BaseModel):
    scenes: list[SceneOut]
    total: int


class VideoListOut(BaseModel):
    videos: list[VideoOut]
    total: int


class ProgressEvent(BaseModel):
    """One SSE message (step 13), e.g. 'storyboard ready' or 'S4 rendering 2/8'."""
    video_id: UUID
    status: VideoStatus
    scene_id: Optional[UUID] = None
    scene_status: Optional[SceneStatus] = None
    message: str
    done: Optional[int] = Field(None, ge=0)
    total: Optional[int] = Field(None, ge=0)
    at: datetime
