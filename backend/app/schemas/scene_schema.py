from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum


class SceneStatus(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class SceneDocument(BaseModel):
    id: str
    prompt: str
    generated_script: Optional[str] = None
    status: SceneStatus
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ScenesListResponse(BaseModel):
    scenes: list[SceneDocument]
    total: int


class QueuedResponse(BaseModel):
    scene_id: str
    status: str
