from typing import Optional, Union
from uuid import UUID

from app.db.models import PipelineEvent, Scene
from app.db.session import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)

IdLike = Union[str, UUID, None]


def _as_uuid(value: IdLike) -> Optional[UUID]:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None


async def record_event(
    *,
    node_name: str,
    status: str,
    video_id: IdLike = None,
    scene_id: IdLike = None,
    model_used: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    latency_ms: Optional[int] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
) -> None:
    """Write one PipelineEvent row. Never raises — a failed write is logged
    and must not fail the LLM call it describes.

    video_id is NOT NULL in the table; if only scene_id is given it is looked
    up from the scene. With neither, there is nothing to attach the row to,
    so it is skipped."""
    v_id, s_id = _as_uuid(video_id), _as_uuid(scene_id)
    if v_id is None and s_id is None:
        return

    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                if v_id is None:
                    scene = await session.get(Scene, s_id)
                    if scene is None:
                        return
                    v_id = scene.video_id
                session.add(
                    PipelineEvent(
                        video_id=v_id,
                        scene_id=s_id,
                        node_name=node_name[:64],
                        model_used=model_used[:64] if model_used else None,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        latency_ms=latency_ms,
                        status=status[:16],
                        input_summary=input_summary,
                        output_summary=output_summary,
                    )
                )
    except Exception:
        logger.exception("Failed to record pipeline event for node '%s'", node_name)
