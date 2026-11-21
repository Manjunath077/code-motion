"""new flow — stage artifacts, decoupled statuses, QA fields

Video:        + current_stage, review_mode, approved_at, spec, outline,
                storyboard_version; - script (unused, replaced by outline)
Scene:        + storyboard, qa_report, audio_hash, code_hash, preview_url
SceneAttempt: + stage, error_class, critic_feedback

Statuses stay VARCHAR(32); allowed values live in app.schemas.status.
Existing rows are not migrated: clear the tables before upgrading (dev data only).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("current_stage", sa.String(length=32), nullable=True))
    op.add_column(
        "videos",
        sa.Column("review_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("videos", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("videos", sa.Column("spec", postgresql.JSONB(), nullable=True))
    op.add_column("videos", sa.Column("outline", postgresql.JSONB(), nullable=True))
    op.add_column(
        "videos",
        sa.Column("storyboard_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_column("videos", "script")

    op.add_column("scenes", sa.Column("storyboard", postgresql.JSONB(), nullable=True))
    op.add_column("scenes", sa.Column("qa_report", postgresql.JSONB(), nullable=True))
    op.add_column("scenes", sa.Column("audio_hash", sa.String(length=64), nullable=True))
    op.add_column("scenes", sa.Column("code_hash", sa.String(length=64), nullable=True))
    op.add_column("scenes", sa.Column("preview_url", sa.Text(), nullable=True))

    op.add_column("scene_attempts", sa.Column("stage", sa.String(length=32), nullable=True))
    op.add_column("scene_attempts", sa.Column("error_class", sa.String(length=32), nullable=True))
    op.add_column("scene_attempts", sa.Column("critic_feedback", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("scene_attempts", "critic_feedback")
    op.drop_column("scene_attempts", "error_class")
    op.drop_column("scene_attempts", "stage")

    op.drop_column("scenes", "preview_url")
    op.drop_column("scenes", "code_hash")
    op.drop_column("scenes", "audio_hash")
    op.drop_column("scenes", "qa_report")
    op.drop_column("scenes", "storyboard")

    op.add_column("videos", sa.Column("script", postgresql.JSONB(), nullable=True))
    op.drop_column("videos", "storyboard_version")
    op.drop_column("videos", "outline")
    op.drop_column("videos", "spec")
    op.drop_column("videos", "approved_at")
    op.drop_column("videos", "review_mode")
    op.drop_column("videos", "current_stage")
