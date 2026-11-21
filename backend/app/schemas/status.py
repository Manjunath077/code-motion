"""Video and scene statuses (NEW_PLAN.md section 5.C).

Stored as plain VARCHAR(32) columns, not Postgres ENUM types, so adding or
renaming a status never needs a migration. These enums are the only place
the allowed values are defined.
"""
from enum import Enum


class VideoStatus(str, Enum):
    # The pipeline, in order. The runner (step 5) advances through these.
    CREATED = "created"
    SPEC = "spec"
    TRACE = "trace"
    OUTLINE = "outline"
    STORYBOARD = "storyboard"
    AWAITING_APPROVAL = "awaiting_approval"
    CODEGEN = "codegen"
    QA = "qa"
    TTS = "tts"
    FINAL_RENDER = "final_render"
    ASSEMBLE = "assemble"
    COMPLETED = "completed"
    # Off-pipeline. Video.current_stage keeps the stage that was running,
    # so the runner knows where to resume.
    FAILED = "failed"
    WAITING_QUOTA = "waiting_quota"


# Statuses that are not pipeline stages: entering one leaves current_stage unchanged.
VIDEO_HALT_STATUSES = frozenset({VideoStatus.FAILED, VideoStatus.WAITING_QUOTA})


class SceneStatus(str, Enum):
    PENDING = "pending"
    CODEGEN = "codegen"
    STATIC_CHECK = "static_check"
    PREVIEW = "preview"
    CRITIC = "critic"
    APPROVED = "approved"
    RENDERED = "rendered"
    FAILED = "failed"
