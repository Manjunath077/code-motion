import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# JSONB on Postgres (indexable, queryable binary JSON); plain JSON on any other
# dialect (e.g. SQLite in unit tests) since JSONB is Postgres-specific.
JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    user_prompt: Mapped[str] = mapped_column(sa.Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    script: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    verified_trace: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    style_guide: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    final_video_url: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    final_audio_url: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(sa.Numeric, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    scenes: Mapped[list["Scene"]] = relationship(back_populates="video", cascade="all, delete-orphan")


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (Index("ix_scenes_video_id_order", "video_id", "order"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    narration_text: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    narration_audio_url: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    narration_duration_seconds: Mapped[Optional[float]] = mapped_column(sa.Numeric, nullable=True)
    visual_description: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    generated_script: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    rendered_segment_url: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    video: Mapped["Video"] = relationship(back_populates="scenes")
    attempts: Mapped[list["SceneAttempt"]] = relationship(back_populates="scene", cascade="all, delete-orphan")


class SceneAttempt(Base):
    __tablename__ = "scene_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    scene_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    generated_script: Mapped[str] = mapped_column(sa.Text, nullable=False)
    validation_result: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    reviewer_feedback: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    is_selected: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now, nullable=False)

    scene: Mapped["Scene"] = relationship(back_populates="attempts")


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_uuid)
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True
    )
    node_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model_used: Mapped[Optional[str]] = mapped_column(sa.String(64), nullable=True)
    tokens_in: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="ok")
    input_summary: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    output_summary: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_now, nullable=False)
